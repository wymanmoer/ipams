import datetime
import json
import mimetypes
import string
import random

import requests
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import DataError, connection
from django.db.models import Count, Subquery, Q, Sum
from django.shortcuts import render
from django.views import View
from django.http import HttpResponse, JsonResponse, HttpResponseRedirect

from accounts.decorators import authorized_roles, authorized_record_user
from accounts.models import User, UserRole, UserRecord, RoleRequest, Log, Student, Setting, Department, Adviser
from ipams import settings
from .forms import CheckedRecordForm, RecordForm
from .models import Record, AuthorRole, Classification, PSCEDClassification, ConferenceLevel, BudgetType, \
    CollaborationType, Author, Conference, PublicationLevel, Publication, Budget, Collaboration, CheckedRecord, Upload, \
    RecordUpload, RecordType, ResearchRecord, CheckedUpload, RecordUploadStatus, RecordDownloadRequest, \
    RecordAuthenticationPin, RecordFile
from django.shortcuts import redirect
from pyexcel_xls import get_data as xls_get
from pyexcel_xlsx import get_data as xlsx_get
from django.utils.datastructures import MultiValueDictKeyError
from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import login_required
from . import forms
from accounts.forms import LoginForm
from records.auxfunctions import *

from axes.models import AccessAttempt, AccessBase
from axes.utils import reset

from django.conf import settings

from django.shortcuts import get_object_or_404, render
from django.views import View
from django.http import HttpResponseRedirect
from .models import Record, RecordFile
from .forms import RecordAuthenticationPinForm
from file_management.models import StudentFolder
from django.urls import reverse
from accounts.models import UserRole
FILE_LENGTH = 5242880


def update_record_tags(request, record_id):
    record = Record.objects.get(pk=record_id)
    ip_is_changed = False
    commercialization_is_changed = False
    community_ext_is_changed = False
    if request.POST.get('ip', 'false') == 'true':
        if not record.is_ip:
            ip_is_changed = True
        record.is_ip = True
    else:
        if record.is_ip:
            ip_is_changed = True
        record.is_ip = False
    if request.POST.get('commercialization', 'false') == 'true':
        if not record.for_commercialization:
            commercialization_is_changed = True
        record.for_commercialization = True
    else:
        if record.for_commercialization:
            commercialization_is_changed = True
        record.for_commercialization = False

    if request.POST.get('community_ext', 'false') == 'true':
        if not record.community_extension:
            community_ext_is_changed = True
        record.community_extension = True
    else:
        if record.community_extension:
            community_ext_is_changed = True
        record.community_extension = False
    record.save()
    status = 'disabled'
    if ip_is_changed:
        if record.is_ip:
            status = 'enabled'
        Log(user=request.user,
            action=f'ip_tag status changed to \"{status}\", record ID: <a href="/dashboard/logs/record/{record_id}">#{record_id}</a>').save()
    if commercialization_is_changed:
        if record.for_commercialization:
            status = 'enabled'
        Log(user=request.user,
            action=f'commercialization_tag status changed to \"{status}\", record ID: <a href="/dashboard/logs/record/{record_id}">#{record_id}</a>').save()

    if community_ext_is_changed:
        if record.community_extension:
            status = 'enabled'
        Log(user=request.user,
            action=f'community_extension_tag status changed to \"{status}\", record ID: <a href="/dashboard/logs/record/{record_id}">#{record_id}</a>').save()
    return {'success': True, 'is-ip': record.is_ip, 'for-commercialization': record.for_commercialization,
            'community-ext': record.community_extension}


# custom function to check the request type since Httpis_ajax(request=request) method is deprecated.
def is_ajax(request):
    return request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest'


class Home(View):
    name = 'records/index.html'

    def get(self, request):
        login_required = request.GET.get('next', False)
        user_roles = UserRole.objects.all()
        departments = Department.objects.all()

        logs = request.session.get('logs', '')
        year_from = request.session.get('year_from', '')
        year_to = request.session.get('year_to', '')
        context = {
            'login_required': login_required,
            'record_form': forms.RecordForm(),
            'login_form': LoginForm(),
            'site_key': settings.GOOGLE_RECAPTCHA_SITE_KEY,
            'test_form': settings.TEST_FORM,
            'user_roles': user_roles,
            'logs': logs,
            'year_from': year_from,
            'year_to': year_to,
            'landing_page': Setting.objects.get(name='landing_page'),

            'departments': departments,
        }
        if logs != '':
            del request.session['logs']
            request.session.modified = True
        return render(request, self.name, context)

    def post(self, request):
        if is_ajax(request=request):
            data = []
            ip_tag = ''
            commercialization_tag = ''
            community_tag = ''
            checked_records = CheckedRecord.objects.filter(status='approved', checked_by__in=Subquery(
                User.objects.filter(role=5).values('pk'))).select_related('record')
            records = Record.objects.filter(pk__in=Subquery(checked_records.values('record_id')))

            # removing accounts
            if request.POST.get('remove-accounts'):
                accounts = request.POST.getlist('accounts[]')
                success = False
                for account_id in accounts:
                    del_account = User.objects.get(pk=int(account_id))
                    if not del_account.is_superuser:
                        del_account.delete()
                        success = True
                return JsonResponse({'success': success})
            # filtering records
            elif request.POST.get('is_filtered') == 'true':
                year_from_filter = request.POST.get('year_from', '0')
                year_to_filter = request.POST.get('year_to', '0')
                classification_filter = request.POST.get('classification')
                psced_classification_filter = request.POST.get('psced_classification')
                author_filter = request.POST.get('author')
                conference_filter = request.POST.get('conference')
                publication_filter = request.POST.get('publication')
                budget_min_filter = request.POST.get('budget_min')
                budget_max_filter = request.POST.get('budget_max')
                collaborator_filter = request.POST.get('collaborator')
                department_filter = request.POST['department']
                ip_filter = request.POST.get('ip_cb')
                commercialization_filter = request.POST.get('commercialization_cb')
                community_filter = request.POST.get('community_cb')

                if (year_from_filter != '' and year_to_filter != ''):
                    records = records.filter(year_accomplished__gte=year_from_filter).filter(
                        year_completed__lte=year_to_filter)
                elif year_from_filter != '':
                    records = records.filter(year_accomplished=year_from_filter)
                elif year_to_filter != '':
                    records = records.filter(year_completed=year_to_filter)

                if ip_filter != '' and commercialization_filter == '' and community_filter == '':
                    records = records.filter(is_ip=True)
                if ip_filter != '' and commercialization_filter != '' and community_filter == '':
                    records = records.filter(Q(is_ip=True) & Q(for_commercialization=True))
                if ip_filter != '' and commercialization_filter == '' and community_filter != '':
                    records = records.filter(Q(is_ip=True) & Q(community_extension=True))
                if commercialization_filter != '' and ip_filter == '' and community_filter == '':
                    records = records.filter(for_commercialization=True)
                if commercialization_filter != '' and ip_filter == '' and community_filter != '':
                    records = records.filter(Q(for_commercialization=True) & Q(community_extension=True))
                if community_filter != '' and commercialization_filter == '' and ip_filter == '':
                    records = records.filter(community_extension=True)
                if ip_filter != '' and commercialization_filter != '' and community_filter != '':
                    records = records.filter(
                        Q(is_ip=True) & Q(for_commercialization=True) & Q(community_extension=True))

                if classification_filter != '':
                    records = records.filter(classification=classification_filter)
                if psced_classification_filter != '':
                    records = records.filter(psced_classification=psced_classification_filter)
                if department_filter != '':
                    records = records.filter(pk__in=Subquery(UserRecord.objects.filter(Q(user__in=Subquery(
                        Student.objects.filter(course__in=Subquery(Course.objects.filter(department__in=Subquery(
                            Department.objects.filter(name=department_filter).values('pk'))).values('pk'))).values(
                            'pk'))) | Q(user__in=Subquery(Adviser.objects.filter(
                        department__in=Subquery(Department.objects.filter(name=department_filter).values('pk'))).values(
                        'pk')))).values('record')))
                if author_filter != '':
                    records = records.filter(
                        pk__in=Author.objects.filter(name__contains=author_filter).values('record_id'))
                if conference_filter != '':
                    records = records.filter(
                        pk__in=Conference.objects.filter(title__contains=conference_filter).values('record_id'))
                if publication_filter != '':
                    publications = Publication.objects.filter(name=publication_filter)
                    if publications.exists():
                        records = records.filter(publication=publications.first())
                if budget_min_filter != "" or budget_max_filter != "":
                    min = 0
                    if budget_min_filter != "":
                        min = float(budget_min_filter)
                    if budget_max_filter != "":
                        max = float(budget_max_filter)
                        records = records.filter(
                            pk__in=Budget.objects.values('record_id').annotate(Sum('budget_allocation')).filter(
                                budget_allocation__sum__range=(min, max)).values('record_id'))
                    else:
                        records = records.filter(
                            pk__in=Budget.objects.values('record_id').annotate(Sum('budget_allocation')).filter(
                                Q(budget_allocation__sum__gte=min)).values('record_id'))
                if collaborator_filter != '':
                    records = records.filter(
                        Q(pk__in=Collaboration.objects.filter(industry__contains=collaborator_filter).values(
                            'record_id')) | Q(
                            pk__in=Collaboration.objects.filter(institution__contains=collaborator_filter).values(
                                'record_id')))
            # accounts role change
            elif request.POST.get('role-change') == 'true':
                accounts = request.POST.getlist('accounts[]')
                accounts_str = ''

                role_id = int(request.POST.get('role-radio'))
                for account_id in accounts:
                    user = User.objects.get(pk=int(account_id))
                    user.role = UserRole.objects.get(pk=role_id)
                    user.save()
                    if account_id == accounts[0]:
                        accounts_str += user.username
                    else:
                        accounts_str += f', {user.username}'
                    RoleRequest.objects.filter(user=user).delete()
                Log(user=request.user,
                    action=f'accounts: {accounts_str} account_role changed to \"{user.role}\" by: {request.user.username}').save()
                # roleRequestNotify(request.user.id, user.id)
                roleRequestApproved(request, request.user.id, user.id)
            # setting datatable records
            for record in records:
                record_conference = Conference.objects.filter(record=record.id)
                if record_conference.exists():
                    for i in record_conference:
                        record_conference_title = i.title
                        record_conference_venue = i.venue
                        if i.conference_level is not None:
                            record_conference_level = i.conference_level.name
                        else:
                            record_conference_level = ''
                else:
                    record_conference_level = ''
                    record_conference_title = ''
                    record_conference_venue = ''

                record_publication = Publication.objects.filter(record=record.id)
                if record_publication.exists():
                    for i in record_publication:
                        record_publication_name = i.name
                        record_publication_isbn = i.isbn
                        record_publication_issn = i.issn
                        record_publication_isi = i.isi
                        if i.publication_level is not None:
                            record_publication_level = i.publication_level.name
                        else:
                            record_publication_level = ''
                else:
                    record_publication_name = ''
                    record_publication_isbn = ''
                    record_publication_issn = ''
                    record_publication_isi = ''
                    record_publication_level = ''

                record_budget = Budget.objects.filter(record=record.id)
                if record_budget.exists():
                    for i in record_budget:
                        record_budget_allocation = i.budget_allocation
                        record_funding_source = i.funding_source
                        if i.budget_type is not None:
                            record_budget_type = i.budget_type.name
                        else:
                            record_budget_type = ''
                else:
                    record_budget_type = ''
                    record_budget_allocation = ''
                    record_funding_source = ''

                record_collaboration = Collaboration.objects.filter(record=record.id)
                if record_collaboration.exists():
                    for i in record_collaboration:
                        record_collaboration_institution = i.institution
                        record_collaboration_industry = i.industry
                        if i.collaboration_type is not None:
                            record_collaboration_type = i.collaboration_type.name
                        else:
                            record_collaboration_type = ''
                else:
                    record_collaboration_type = ''
                    record_collaboration_institution = ''
                    record_collaboration_industry = ''

                if record.is_ip == True:
                    ip_tag = 'Intellectual Property'
                if record.for_commercialization == True:
                    commercialization_tag = 'Commercialization'
                if record.community_extension == True:
                    community_tag = 'Community Extension'

                if request.user.is_anonymous:
                    data.append([
                        record.pk,
                        # additional
                        record.representative,
                        record_conference_level,
                        record_conference_title,
                        record_conference_venue,
                        record_publication_name,
                        record_publication_isbn,
                        record_publication_issn,
                        record_publication_isi,
                        record_publication_level,
                        record_budget_type,
                        record_budget_allocation,
                        record_funding_source,
                        record_collaboration_type,
                        record_collaboration_institution,
                        record_collaboration_industry,
                        ip_tag,
                        commercialization_tag,
                        community_tag,
                        record.abstract,
                        # visible
                        '<a href="/record/' + str(
                            record.pk) + '">' + record.title + '</a>',
                        record.year_accomplished,
                        record.classification.name,
                        record.psced_classification.name,
                    ])
                else:
                    if request.user.role.pk > 2:
                        data.append([
                            record.pk,
                            # additional
                            record.representative,
                            record_conference_level,
                            record_conference_title,
                            record_conference_venue,
                            record_publication_name,
                            record_publication_isbn,
                            record_publication_issn,
                            record_publication_isi,
                            record_publication_level,
                            record_budget_type,
                            record_budget_allocation,
                            record_funding_source,
                            record_collaboration_type,
                            record_collaboration_institution,
                            record_collaboration_industry,
                            ip_tag,
                            commercialization_tag,
                            community_tag,
                            record.abstract,
                            # visible
                            '<a href="/record/' + str(
                                record.pk) + '">' + record.title + '</a>',
                            record.year_accomplished,
                            record.year_completed,
                            record.classification.name,
                            record.psced_classification.name,
                        ])
                    else:
                        data.append([
                            record.pk,
                            # additional
                            record.representative,
                            record_conference_level,
                            record_conference_title,
                            record_conference_venue,
                            record_publication_name,
                            record_publication_isbn,
                            record_publication_issn,
                            record_publication_isi,
                            record_publication_level,
                            record_budget_type,
                            record_budget_allocation,
                            record_funding_source,
                            record_collaboration_type,
                            record_collaboration_institution,
                            record_collaboration_industry,
                            ip_tag,
                            commercialization_tag,
                            community_tag,
                            record.abstract,
                            # visible
                            '<a href="/record/' + str(
                                record.pk) + '">' + record.title + '</a>',
                            record.year_accomplished,
                            record.classification.name,
                            record.psced_classification.name,
                        ])

            return JsonResponse({"data": data})


# Manage documents table
class ViewManageDocuments(View):
    name = 'records/dashboard/manage_documents.html'
    record_uploads = RecordUpload.objects.all()
    record_upload_status = RecordUploadStatus.objects.all()
    context = {
        'record_uploads': record_uploads,
        'record_upload_status': record_upload_status,
    }

    @method_decorator(authorized_roles(roles=['adviser', 'ktto', 'rdco', 'tbi', 'itso']))
    @method_decorator(login_required(login_url='/'))
    def get(self, request):
        return render(request, self.name, self.context)

    def post(self, request):
        if is_ajax(request=request):
            if request.POST.get('status_change', False) == 'true':
                record_upload = RecordUpload.objects.get(pk=int(request.POST.get('record_upload_id', 0)))
                record_upload.record_upload_status = RecordUploadStatus.objects.get(pk=request.POST.get('status', 0))
                record_upload.save()
                Log(user=request.user,
                    action=f'{record_upload.upload.name}_document status changed to \"{record_upload.record_upload_status}\", record ID: <a href="/dashboard/logs/record/{record_upload.record.pk}">#{record_upload.record.pk}</a>').save()
                return JsonResponse({'success': True})
            else:
                data = []
                record_uploads = RecordUpload.objects.all()
                if request.POST.get('is-filter', '0') == '1' and request.POST.get('record-upload-status', '0') != '0':
                    record_uploads = record_uploads.filter(record_upload_status=RecordUploadStatus.objects.get(
                        pk=request.POST.get('record-upload-status', '0')))
                for record_upload in record_uploads:
                    data.append([record_upload.pk,
                                 record_upload.upload.name,
                                 f'<a href="/dashboard/manage/documents/record/{record_upload.record.pk}">{record_upload.record.title}</a>',
                                 f'{record_upload.record.record_type.name}',
                                 f'{record_upload.date_uploaded.strftime("%Y-%m-%d %H:%M:%S")}',
                                 f'<button type="button" onclick="onStatusChangeClick({record_upload.pk}, {record_upload.record_upload_status.pk});">Change</button> {record_upload.record_upload_status.name} ',
                                 f'<a href="/download/document/{record_upload.pk}">Download</a>'])
                return JsonResponse({"data": data})


# Manage documents template
class ViewManageDocumentsRecord(View):
    name = 'records/dashboard/manage_documents_record.html'
    author_roles = AuthorRole.objects.all()
    classifications = Classification.objects.all()
    psced_classifications = PSCEDClassification.objects.all().order_by('name')
    conference_levels = ConferenceLevel.objects.all()
    budget_types = BudgetType.objects.all()
    collaboration_types = CollaborationType.objects.all()
    publication_levels = PublicationLevel.objects.all()
    uploads = Upload.objects.all()
    checked_record_form = CheckedRecordForm()
    context = {
        'author_roles': author_roles,
        'classifications': classifications,
        'psced_classifications': psced_classifications,
        'conference_levels': conference_levels,
        'budget_types': budget_types,
        'collaboration_types': collaboration_types,
        'publication_levels': publication_levels,
        'uploads': uploads,
        'checked_record_form': checked_record_form,
        'is_owner': True,
    }

    @method_decorator(login_required(login_url='/'))
    @method_decorator(authorized_record_user())
    def get(self, request, record_id):
        owners = UserRecord.objects.filter(record=Record.objects.get(pk=record_id))
        self.context['owners'] = owners
        checked_records = CheckedRecord.objects.filter(record=Record.objects.get(pk=record_id))
        adviser_checked = {'status': 'pending'}
        ktto_checked = {'status': 'pending'}
        rdco_checked = {'status': 'pending'}
        role_checked = False
        record = Record.objects.get(pk=record_id)
        research_record = ResearchRecord.objects.filter(Q(proposal=record) | Q(research=record)).first()
        for checked_record in checked_records:
            if checked_record.checked_by.role.id == 3:
                adviser_checked = {'status': checked_record.status, 'content': checked_record}
            if checked_record.checked_by.role.id == 4 or checked_record.checked_by.role.id == 7:
                ktto_checked = {'status': checked_record.status, 'content': checked_record}
            if checked_record.checked_by.role.id == 5:
                rdco_checked = {'status': checked_record.status, 'content': checked_record}
            if checked_record.checked_by.role.id == request.user.role.pk:
                role_checked = True
        self.context['adviser_checked'] = adviser_checked
        self.context['ktto_checked'] = ktto_checked
        self.context['rdco_checked'] = rdco_checked
        self.context['role_checked'] = role_checked
        self.context['record'] = record
        self.context['is_removable'] = True
        self.context['research_record'] = research_record
        return render(request, self.name, self.context)

    def post(self, request, record_id):
        if is_ajax(request=request):
            # removing record
            if request.POST.get('remove', 'false') == 'true':
                del_record = Record.objects.get(pk=record_id)
                del_record.abstract_file.delete()
                del_record_uploads = RecordUpload.objects.filter(record=del_record)
                for del_record_upload in del_record_uploads:
                    del_record_upload.file.delete()
                del_record.delete()
                return JsonResponse({'success': True})
            # updating record tags
            elif request.POST.get('tags_update', 'false') == 'true':
                return JsonResponse(update_record_tags(request, record_id))
            # get uploaded document data
            elif request.POST.get('get_document', 'false') == 'true':
                upload = Upload.objects.get(pk=request.POST.get('upload_id', 0))
                record = Record.objects.get(pk=request.POST.get('record_id', 0))
                record_upload = RecordUpload.objects.filter(upload=upload, record=record).first()
                checked_uploads = CheckedUpload.objects.filter(record_upload=record_upload).order_by('-date_checked')
                comments = []
                checked_bys = []
                checked_dates = []
                for checked_upload in checked_uploads:
                    comments.append(checked_upload.comment)
                    checked_bys.append(checked_upload.checked_by.username)
                    checked_dates.append(checked_upload.date_checked)
                if record_upload is None:
                    return JsonResponse({'success': False, 'doc-title': upload.name})
                else:
                    return JsonResponse({'success': True,
                                         'doc-title': record_upload.upload.name,
                                         'doc-status': record_upload.record_upload_status.name,
                                         'is-ip': record_upload.is_ip,
                                         'for-commercialization': record_upload.for_commercialization,
                                         'comments': comments,
                                         'checked_bys': checked_bys,
                                         'checked_dates': checked_dates,
                                         'record-upload-id': record_upload.pk})
            # POSTING COMMENTS
            elif request.POST.get('post_comment', 'false') == 'true':
                upload = Upload.objects.get(pk=request.POST.get('upload_id', 0))
                record = Record.objects.get(pk=request.POST.get('record_id', 0))
                comment = request.POST.get('comment', '')
                record_upload = RecordUpload.objects.filter(upload=upload, record=record).first()
                CheckedUpload(comment=comment, checked_by=request.user, record_upload=record_upload).save()
                return JsonResponse({'success': True})
            else:
                return JsonResponse({'success': False})
        else:
            # approving or declining record
            if request.user.role.id > 2:
                checked_record_form = CheckedRecordForm(request.POST)
                if checked_record_form.is_valid():
                    checked_record = checked_record_form.save(commit=False)
                    checked_record.checked_by = request.user
                    checked_record.record = Record.objects.get(pk=record_id)
                    checked_record.status = request.POST.get('status')
                    checked_record.save()
                else:
                    print('invalid form')
                return redirect('records-view', record_id)


class ViewRecord(View):
    name = 'records/pin.html'
    author_roles = AuthorRole.objects.all()
    classifications = Classification.objects.all()
    psced_classifications = PSCEDClassification.objects.all().order_by('name')
    conference_levels = ConferenceLevel.objects.all()
    budget_types = BudgetType.objects.all()
    collaboration_types = CollaborationType.objects.all()
    publication_levels = PublicationLevel.objects.all()
    uploads = Upload.objects.all()
    checked_record_form = CheckedRecordForm()
    context = {
        'author_roles': author_roles,
        'classifications': classifications,
        'psced_classifications': psced_classifications,
        'conference_levels': conference_levels,
        'budget_types': budget_types,
        'collaboration_types': collaboration_types,
        'publication_levels': publication_levels,
        'uploads': uploads,
        'checked_record_form': checked_record_form,
    }

    @method_decorator(login_required(login_url='/'))
    @method_decorator(authorized_record_user())
    def get(self, request, record_id):
        checked_records = CheckedRecord.objects.filter(record=Record.objects.get(pk=record_id))
        is_removable = False
        record = Record.objects.get(pk=record_id)
        record_uploads = record.recordupload_set.all()
        for checked_record in checked_records:
            if checked_record.status == 'declined':
                is_removable = True
        self.context['record'] = Record.objects.get(pk=record_id)
        self.context['is_removable'] = is_removable
        self.context['recorduploads'] = record_uploads
        return render(request, self.name, self.context)

    def post(self, request, record_id):
        if is_ajax(request=request):
            # updating record tags
            if request.POST.get('tags_update', 'false') == 'true':
                return JsonResponse(update_record_tags(request, record_id))

            # send download request
            if request.POST.get('sendRequest'):
                record_id = request.POST.get('recordId')
                user_id = request.POST.get('userId')
                download_request = RecordDownloadRequest(sent_by=User.objects.get(pk=user_id),
                                                         record=Record.objects.get(pk=record_id))
                download_request.save()
                sendDownloadRequest(request, request.user.id, record_id)
                return JsonResponse({'success': True})


            # get uploaded document data
            elif request.POST.get('get_document', 'false') == 'true':
                upload = Upload.objects.get(pk=request.POST.get('upload_id', 0))
                record = Record.objects.get(pk=request.POST.get('record_id', 0))
                record_upload = RecordUpload.objects.filter(upload=upload, record=record).first()
                checked_uploads = CheckedUpload.objects.filter(record_upload=record_upload).order_by('-date_checked')
                comments = []
                checked_bys = []
                checked_dates = []
                for checked_upload in checked_uploads:
                    comments.append(checked_upload.comment)
                    checked_bys.append(checked_upload.checked_by.username)
                    checked_dates.append(checked_upload.date_checked)
                if record_upload is None:
                    return JsonResponse({'success': False, 'doc-title': upload.name})
                else:
                    return JsonResponse({'success': True,
                                         'doc-title': record_upload.upload.name,
                                         'doc-status': record_upload.record_upload_status.name,
                                         'is-ip': record_upload.is_ip,
                                         'for-commercialization': record_upload.for_commercialization,
                                         'comments': comments,
                                         'checked_bys': checked_bys,
                                         'checked_dates': checked_dates,
                                         'record-upload-id': record_upload.pk})
            # POSTING COMMENTS
            elif request.POST.get('post_comment', 'false') == 'true':
                upload = Upload.objects.get(pk=request.POST.get('upload_id', 0))
                record = Record.objects.get(pk=request.POST.get('record_id', 0))
                comment = request.POST.get('comment', '')
                record_upload = RecordUpload.objects.filter(upload=upload, record=record).first()
                CheckedUpload(comment=comment, checked_by=request.user,
                              record_upload=record_upload).save()
                return JsonResponse({'success': True})
            else:
                return JsonResponse({'success': False})


# Pending template view
class PendingRecordView(View):
    name = 'records/profile/view_pending.html'
    author_roles = AuthorRole.objects.all()
    classifications = Classification.objects.all()
    psced_classifications = PSCEDClassification.objects.all().order_by('name')
    conference_levels = ConferenceLevel.objects.all()
    budget_types = BudgetType.objects.all()
    collaboration_types = CollaborationType.objects.all()
    publication_levels = PublicationLevel.objects.all()
    uploads = Upload.objects.all()
    checked_record_form = CheckedRecordForm()
    context = {
        'author_roles': author_roles,
        'classifications': classifications,
        'psced_classifications': psced_classifications,
        'conference_levels': conference_levels,
        'budget_types': budget_types,
        'collaboration_types': collaboration_types,
        'publication_levels': publication_levels,
        'uploads': uploads,
        'checked_record_form': checked_record_form,
    }

    @method_decorator(login_required(login_url='/'))
    def get(self, request, record_id):
        owners = UserRecord.objects.filter(record=Record.objects.get(pk=record_id))
        self.context['owners'] = owners
        checked_records = CheckedRecord.objects.filter(record=Record.objects.get(pk=record_id))
        adviser_checked = {'status': 'pending'}
        ktto_checked = {'status': 'pending'}
        rdco_checked = {'status': 'pending'}
        role_checked = False
        is_owner = False
        is_removable = False
        if request.user.role.pk > 3:
            is_removable = True
        for checked_record in checked_records:
            if checked_record.checked_by.role.id == 3:
                adviser_checked = {'status': checked_record.status, 'content': checked_record}
            if checked_record.checked_by.role.id == 4 or checked_record.checked_by.role.id == 7:
                ktto_checked = {'status': checked_record.status, 'content': checked_record}
            if checked_record.checked_by.role.id == 5:
                rdco_checked = {'status': checked_record.status, 'content': checked_record}
            if checked_record.checked_by.role.id == request.user.role.pk:
                role_checked = True
            if checked_record.status == 'declined':
                is_removable = True
        if UserRecord.objects.filter(user=request.user, record=Record.objects.get(pk=record_id)):
            is_owner = True
        self.context['adviser_checked'] = adviser_checked
        self.context['ktto_checked'] = ktto_checked
        self.context['rdco_checked'] = rdco_checked
        self.context['role_checked'] = role_checked
        self.context['record'] = Record.objects.get(pk=record_id)
        self.context['is_owner'] = is_owner
        self.context['is_removable'] = is_removable
        return render(request, self.name, self.context)

    def post(self, request, record_id):
        if is_ajax(request=request):
            # removing record
            if request.POST.get('deleteRecord', 'false') == 'true':
                reason = request.POST.get('reason')
                recordTitle = request.POST.get('recordTitle')
                record = Record.objects.get(title=recordTitle)
                record.is_marked = True
                record.reason = reason
                record.save()
                deleteRecord(request, request.user.id, record.pk, reason)
                return JsonResponse({'success': True})
            # if request.POST.get('remove', 'false') == 'true':
            #     del_record = Record.objects.get(pk=record_id)
            #     del_record.abstract_file.delete()
            #     del_record.delete()
            #     return JsonResponse({'success': True})

            # updating record tags
            elif request.POST.get('tags_update', 'false') == 'true':
                return JsonResponse(update_record_tags(request, record_id))
            # get uploaded document data
            elif request.POST.get('get_document', 'false') == 'true':
                upload = Upload.objects.get(pk=request.POST.get('upload_id', 0))
                record = Record.objects.get(pk=request.POST.get('record_id', 0))
                record_upload = RecordUpload.objects.filter(upload=upload, record=record).first()
                checked_uploads = CheckedUpload.objects.filter(record_upload=record_upload).order_by('-date_checked')
                comments = []
                checked_bys = []
                checked_dates = []
                for checked_upload in checked_uploads:
                    comments.append(checked_upload.comment)
                    checked_bys.append(checked_upload.checked_by.username)
                    checked_dates.append(checked_upload.date_checked)
                if record_upload is None:
                    return JsonResponse({'success': False, 'doc-title': upload.name})
                else:
                    return JsonResponse({'success': True,
                                         'doc-title': record_upload.upload.name,
                                         'is-ip': record_upload.is_ip,
                                         'for-commercialization': record_upload.for_commercialization,
                                         'comments': comments,
                                         'checked_bys': checked_bys,
                                         'checked_dates': checked_dates,
                                         'record-upload-id': record_upload.pk})
            # POSTING COMMENTS ON CHECKED RECORD
            elif request.POST.get('post_comment', 'false') == 'true':
                upload = Upload.objects.get(pk=request.POST.get('upload_id', 0))
                record = Record.objects.get(pk=request.POST.get('record_id', 0))
                comment = request.POST.get('comment', '')
                record_upload = RecordUpload.objects.filter(upload=upload, record=record).first()
                CheckedUpload(comment=comment, checked_by=request.user,
                              record_upload=record_upload).save()

                recordComment(request, request.user.id, record.id, UserRecord.objects.get(record=record.id).user.id)
                return JsonResponse({'success': True})
            else:
                return JsonResponse({'success': False})
        else:
            # Approving or declining record
            if request.user.role.id > 2:
                checked_record_form = CheckedRecordForm(request.POST)
                if checked_record_form.is_valid():
                    checked_record = checked_record_form.save(commit=False)
                    checked_record.checked_by = request.user
                    checked_record.record = Record.objects.get(pk=record_id)
                    checked_record.status = request.POST.get('status')
                    checked_record.save()

                    status = request.POST.get('status')

                    # Check if the status is 'approved' and the user is an RDcO
                    if status == 'approved' and request.user.role.id == 5:
                        # Get the student role ID (you can also get this from the database)
                        student_role_id = 2  # Assuming 2 represents the student role

                        # Create a name for the folder (you may need to modify this logic)
                        # For example, you can keep track of the count of folders created by students
                        # and increment it for each new folder.
                        folder_count = StudentFolder.objects.filter(role__id=student_role_id).count()
                        folder_name = f"Project {folder_count + 1}"  # Create a name like "Project 1", "Project 2", etc.

                        # Get the student user (the user who added the record)
                        # You can use the `added_by` field from the Record model
                        added_by_user = Record.objects.get(pk=record_id).added_by

                        # Create a StudentFolder with the role set to the student role instance
                        student_role = UserRole.objects.get(pk=student_role_id)
                        student_folder = StudentFolder(
                            name=folder_name,
                            user=added_by_user,
                            record=Record.objects.get(pk=record_id),
                            role=student_role
                        )
                        student_folder.save()

                        # Redirect to a success page (modify the URL as needed)
                        return redirect('records-pending')



# display all delete record requests to table
def get_all_delete_requests(request):
    if request.method == 'POST':
        data = []
        delete_pendings = Record.objects.filter(is_marked=True)
        for record in delete_pendings:
            data.append([
                record.pk,
                f'<a href="/record/pending/delete/request/{record.pk}">{record.title}</a>',
                record.reason,
            ])

        return JsonResponse({'data': data})


# template view when selecting from pending delete requests table
class PendingDeleteRecordsView(View):
    name = 'records/profile/pending_delete_records.html'
    author_roles = AuthorRole.objects.all()
    classifications = Classification.objects.all()
    psced_classifications = PSCEDClassification.objects.all().order_by('name')
    conference_levels = ConferenceLevel.objects.all()
    budget_types = BudgetType.objects.all()
    collaboration_types = CollaborationType.objects.all()
    publication_levels = PublicationLevel.objects.all()
    uploads = Upload.objects.all()
    checked_record_form = CheckedRecordForm()
    context = {
        'author_roles': author_roles,
        'classifications': classifications,
        'psced_classifications': psced_classifications,
        'conference_levels': conference_levels,
        'budget_types': budget_types,
        'collaboration_types': collaboration_types,
        'publication_levels': publication_levels,
        'uploads': uploads,
        'checked_record_form': checked_record_form,
    }

    @method_decorator(login_required(login_url='/'))
    def get(self, request, record_id):
        owners = UserRecord.objects.filter(record=Record.objects.get(pk=record_id))
        self.context['owners'] = owners
        checked_records = CheckedRecord.objects.filter(record=Record.objects.get(pk=record_id))
        role_checked = False
        is_owner = False
        is_removable = False
        if request.user.role.pk > 3:
            is_removable = True
        for checked_record in checked_records:
            if checked_record.checked_by.role.id == request.user.role.pk:
                role_checked = True
            if checked_record.status == 'declined':
                is_removable = True
        if UserRecord.objects.filter(user=request.user, record=Record.objects.get(pk=record_id)):
            is_owner = True
        self.context['role_checked'] = role_checked
        self.context['record'] = Record.objects.get(pk=record_id)
        self.context['is_owner'] = is_owner
        self.context['is_removable'] = is_removable
        self.context['reason'] = Record.objects.get(pk=record_id).reason
        self.context['delete_request'] = Record.objects.filter(is_marked=True)
        return render(request, self.name, self.context)

    def post(self, request, record_id):
        if request.method == 'POST':
            # removing record
            if 'approvedRequestBtn' in request.POST:
                record_id = request.POST.get('record_number')
                del_record = Record.objects.get(pk=record_id)
                user_record = UserRecord.objects.get(record=Record.objects.get(pk=record_id))
                del_record.abstract_file.delete()
                del_record_uploads = RecordUpload.objects.filter(record=del_record)
                for del_record_upload in del_record_uploads:
                    del_record_upload.file.delete()
                approvedDeleteRecord(request, request.user.id, record_id, user_record.user.pk, del_record.reason)
                del_record.delete()
                return redirect("records-pending")
            else:
                messages.error(request, 'Error encountered while approving record')
                return redirect("records-pending")

        if is_ajax(request=request):
            # get uploaded document data
            if request.POST.get('get_document', 'false') == 'true':
                upload = Upload.objects.get(pk=request.POST.get('upload_id', 0))
                record = Record.objects.get(pk=request.POST.get('record_id', 0))
                record_upload = RecordUpload.objects.filter(upload=upload, record=record).first()
                checked_uploads = CheckedUpload.objects.filter(record_upload=record_upload).order_by('-date_checked')
                comments = []
                checked_bys = []
                checked_dates = []
                for checked_upload in checked_uploads:
                    comments.append(checked_upload.comment)
                    checked_bys.append(checked_upload.checked_by.username)
                    checked_dates.append(checked_upload.date_checked)
                if record_upload is None:
                    return JsonResponse({'success': False, 'doc-title': upload.name})
                else:
                    return JsonResponse({'success': True,
                                         'doc-title': record_upload.upload.name,
                                         'is-ip': record_upload.is_ip,
                                         'for-commercialization': record_upload.for_commercialization,
                                         'comments': comments,
                                         'checked_bys': checked_bys,
                                         'checked_dates': checked_dates,
                                         'record-upload-id': record_upload.pk})
            else:
                return JsonResponse({'success': False})

            # return redirect('records-pending')


# template view when selecting from my records table
class MyRecordView(View):
    name = 'records/profile/view_myrecords.html'
    author_roles = AuthorRole.objects.all()
    classifications = Classification.objects.all()
    psced_classifications = PSCEDClassification.objects.all().order_by('name')
    conference_levels = ConferenceLevel.objects.all()
    budget_types = BudgetType.objects.all()
    collaboration_types = CollaborationType.objects.all()
    publication_levels = PublicationLevel.objects.all()
    uploads = Upload.objects.all()
    checked_record_form = CheckedRecordForm()
    context = {
        'author_roles': author_roles,
        'classifications': classifications,
        'psced_classifications': psced_classifications,
        'conference_levels': conference_levels,
        'budget_types': budget_types,
        'collaboration_types': collaboration_types,
        'publication_levels': publication_levels,
        'uploads': uploads,
        'checked_record_form': checked_record_form,
        'is_owner': True,
    }

    @method_decorator(login_required(login_url='/'))
    @method_decorator(authorized_record_user())
    def get(self, request, record_id):
        owners = UserRecord.objects.filter(record=Record.objects.get(pk=record_id))
        self.context['owners'] = owners
        checked_records = CheckedRecord.objects.filter(record=Record.objects.get(pk=record_id))
        adviser_checked = {'status': 'pending'}
        ktto_checked = {'status': 'pending'}
        rdco_checked = {'status': 'pending'}
        role_checked = False
        is_removable = False
        record = Record.objects.get(pk=record_id)
        research_record = ResearchRecord.objects.filter(Q(proposal=record) | Q(research=record)).first()
        if request.user.role.pk > 3:
            is_removable = True
        for checked_record in checked_records:
            if checked_record.checked_by.role.id == 3:
                adviser_checked = {'status': checked_record.status, 'content': checked_record}
            if checked_record.checked_by.role.id == 4 or checked_record.checked_by.role.id == 7:
                ktto_checked = {'status': checked_record.status, 'content': checked_record}
            if checked_record.checked_by.role.id == 5:
                rdco_checked = {'status': checked_record.status, 'content': checked_record}
            if checked_record.checked_by.role.id == request.user.role.pk:
                role_checked = True
            if checked_record.status == 'declined':
                is_removable = True
        if adviser_checked['status'] == 'pending' and ktto_checked['status'] == 'pending' and rdco_checked[
            'status'] == 'pending':
            is_removable = True
        record_uploads = record.recordupload_set.all()
        self.context['adviser_checked'] = adviser_checked
        self.context['ktto_checked'] = ktto_checked
        self.context['rdco_checked'] = rdco_checked
        self.context['role_checked'] = role_checked
        self.context['record'] = record
        self.context['is_removable'] = is_removable
        self.context['research_record'] = research_record
        self.context['recorduploads'] = record_uploads
        return render(request, self.name, self.context)

    def post(self, request, record_id):
        if is_ajax(request=request):
            # removing record
            if request.POST.get('deleteRecord', 'false') == 'true':
                reason = request.POST.get('reason')
                recordTitle = request.POST.get('recordTitle')
                record = Record.objects.get(title=recordTitle)
                record.is_marked = True
                record.reason = reason
                record.save()
                deleteRecord(request, request.user.id, record.pk, reason)
                return JsonResponse({'success': True})

            # if request.POST.get('remove', 'false') == 'true':
            #     del_record = Record.objects.get(pk=record_id)
            #     del_record.abstract_file.delete()
            #     del_record_uploads = RecordUpload.objects.filter(record=del_record)
            #     for del_record_upload in del_record_uploads:
            #         del_record_upload.file.delete()
            #     del_record.delete()
            #     return JsonResponse({'success': True})

            # resubmitting
            if request.POST.get('resubmit', 'false') == 'true':
                checked_record = CheckedRecord.objects.get(record=Record.objects.get(pk=record_id), status='declined')
                recipient = checked_record
                checked_record.delete()
                resubmission(request, request.user.id, record_id, recipient)
                return JsonResponse({'success': True})
            # updating record tags
            elif request.POST.get('tags_update', 'false') == 'true':
                return JsonResponse(update_record_tags(request, record_id))
            # get uploaded document data
            elif request.POST.get('get_document', 'false') == 'true':
                upload = Upload.objects.get(pk=request.POST.get('upload_id', 0))
                record = Record.objects.get(pk=request.POST.get('record_id', 0))
                record_upload = RecordUpload.objects.filter(upload=upload, record=record).first()
                checked_uploads = CheckedUpload.objects.filter(record_upload=record_upload).order_by('-date_checked')
                comments = []
                checked_bys = []
                checked_dates = []
                for checked_upload in checked_uploads:
                    comments.append(checked_upload.comment)
                    checked_bys.append(checked_upload.checked_by.username)
                    checked_dates.append(checked_upload.date_checked)
                if record_upload is None:
                    return JsonResponse({'success': False, 'doc-title': upload.name})
                else:
                    return JsonResponse({'success': True,
                                         'doc-title': record_upload.upload.name,
                                         'doc-status': record_upload.record_upload_status.name,
                                         'is-ip': record_upload.is_ip,
                                         'for-commercialization': record_upload.for_commercialization,
                                         'comments': comments,
                                         'checked_bys': checked_bys,
                                         'checked_dates': checked_dates,
                                         'record-upload-id': record_upload.pk})
            # POSTING COMMENTS
            elif request.POST.get('post_comment', 'false') == 'true':
                upload = Upload.objects.get(pk=request.POST.get('upload_id', 0))
                record = Record.objects.get(pk=request.POST.get('record_id', 0))
                comment = request.POST.get('comment', '')
                record_upload = RecordUpload.objects.filter(upload=upload, record=record).first()
                CheckedUpload(comment=comment, checked_by=request.user, record_upload=record_upload).save()
                return JsonResponse({'success': True})
            else:
                return JsonResponse({'success': False})
        else:
            # approving or declining record
            if request.user.role.id > 2:
                checked_record_form = CheckedRecordForm(request.POST)
                if checked_record_form.is_valid():
                    checked_record = checked_record_form.save(commit=False)
                    checked_record.checked_by = request.user
                    checked_record.record = Record.objects.get(pk=record_id)
                    checked_record.status = request.POST.get('status')
                    checked_record.save()
                else:
                    print('invalid form')
                return redirect('records-myrecords')


class ApprovedRecordView(View):
    name = 'records/profile/view_approved.html'
    author_roles = AuthorRole.objects.all()
    classifications = Classification.objects.all()
    psced_classifications = PSCEDClassification.objects.all().order_by('name')
    conference_levels = ConferenceLevel.objects.all()
    budget_types = BudgetType.objects.all()
    collaboration_types = CollaborationType.objects.all()
    publication_levels = PublicationLevel.objects.all()
    uploads = Upload.objects.all()
    checked_record_form = CheckedRecordForm()
    context = {
        'author_roles': author_roles,
        'classifications': classifications,
        'psced_classifications': psced_classifications,
        'conference_levels': conference_levels,
        'budget_types': budget_types,
        'collaboration_types': collaboration_types,
        'publication_levels': publication_levels,
        'uploads': uploads,
        'checked_record_form': checked_record_form,
    }

    @method_decorator(login_required(login_url='/'))
    def get(self, request, record_id):
        owners = UserRecord.objects.filter(record=Record.objects.get(pk=record_id))
        self.context['owners'] = owners
        checked_records = CheckedRecord.objects.filter(record=Record.objects.get(pk=record_id))
        adviser_checked = {'status': 'pending'}
        ktto_checked = {'status': 'pending'}
        rdco_checked = {'status': 'pending'}
        role_checked = False
        is_owner = False
        is_removable = False
        if request.user.role.pk > 3:
            is_removable = True
        for checked_record in checked_records:
            if checked_record.checked_by.role.id == 3:
                adviser_checked = {'status': checked_record.status, 'content': checked_record}
            if checked_record.checked_by.role.id == 4 or checked_record.checked_by.role.id == 7:
                ktto_checked = {'status': checked_record.status, 'content': checked_record}
            if checked_record.checked_by.role.id == 5:
                rdco_checked = {'status': checked_record.status, 'content': checked_record}
            if checked_record.checked_by.role.id == request.user.role.pk:
                role_checked = True
            if checked_record.status == 'declined':
                is_removable = True
        if UserRecord.objects.filter(user=request.user, record=Record.objects.get(pk=record_id)):
            is_owner = True
        self.context['adviser_checked'] = adviser_checked
        self.context['ktto_checked'] = ktto_checked
        self.context['rdco_checked'] = rdco_checked
        self.context['role_checked'] = role_checked
        self.context['record'] = Record.objects.get(pk=record_id)
        self.context['is_owner'] = is_owner
        self.context['is_removable'] = is_removable
        return render(request, self.name, self.context)

    def post(self, request, record_id):
        if is_ajax(request=request):
            # removing record
            if request.POST.get('remove', 'false') == 'true':
                del_record = Record.objects.get(pk=record_id)
                del_record.abstract_file.delete()
                del_record.delete()
                return JsonResponse({'success': True})
            # updating record tags
            elif request.POST.get('tags_update', 'false') == 'true':
                return JsonResponse(update_record_tags(request, record_id))
            # get uploaded document data
            elif request.POST.get('get_document', 'false') == 'true':
                upload = Upload.objects.get(pk=request.POST.get('upload_id', 0))
                record = Record.objects.get(pk=request.POST.get('record_id', 0))
                record_upload = RecordUpload.objects.filter(upload=upload, record=record).first()
                checked_uploads = CheckedUpload.objects.filter(record_upload=record_upload).order_by('-date_checked')
                comments = []
                checked_bys = []
                checked_dates = []
                for checked_upload in checked_uploads:
                    comments.append(checked_upload.comment)
                    checked_bys.append(checked_upload.checked_by.username)
                    checked_dates.append(checked_upload.date_checked)
                if record_upload is None:
                    return JsonResponse({'success': False, 'doc-title': upload.name})
                else:
                    return JsonResponse({'success': True,
                                         'doc-title': record_upload.upload.name,
                                         'is-ip': record_upload.is_ip,
                                         'for-commercialization': record_upload.for_commercialization,
                                         'comments': comments,
                                         'checked_bys': checked_bys,
                                         'checked_dates': checked_dates,
                                         'record-upload-id': record_upload.pk})
            # POSTING COMMENTS
            elif request.POST.get('post_comment', 'false') == 'true':
                upload = Upload.objects.get(pk=request.POST.get('upload_id', 0))
                record = Record.objects.get(pk=request.POST.get('record_id', 0))
                comment = request.POST.get('comment', '')
                record_upload = RecordUpload.objects.filter(upload=upload, record=record).first()
                CheckedUpload(comment=comment, checked_by=request.user,
                              record_upload=record_upload).save()
                return JsonResponse({'success': True})
            else:
                return JsonResponse({'success': False})
        else:
            # approving or declining record
            if request.user.role.id > 2:
                checked_record_form = CheckedRecordForm(request.POST)
                if checked_record_form.is_valid():
                    checked_record = checked_record_form.save(commit=False)
                    checked_record.checked_by = request.user
                    checked_record.record = Record.objects.get(pk=record_id)
                    checked_record.status = request.POST.get('status')
                    checked_record.save()
                else:
                    print('invalid form')
                return redirect('records-approved')


class DeclinedRecordView(View):
    name = 'records/profile/view_declined.html'
    author_roles = AuthorRole.objects.all()
    classifications = Classification.objects.all()
    psced_classifications = PSCEDClassification.objects.all().order_by('name')
    conference_levels = ConferenceLevel.objects.all()
    budget_types = BudgetType.objects.all()
    collaboration_types = CollaborationType.objects.all()
    publication_levels = PublicationLevel.objects.all()
    uploads = Upload.objects.all()
    checked_record_form = CheckedRecordForm()
    context = {
        'author_roles': author_roles,
        'classifications': classifications,
        'psced_classifications': psced_classifications,
        'conference_levels': conference_levels,
        'budget_types': budget_types,
        'collaboration_types': collaboration_types,
        'publication_levels': publication_levels,
        'uploads': uploads,
        'checked_record_form': checked_record_form,
    }

    @method_decorator(login_required(login_url='/'))
    def get(self, request, record_id):
        owners = UserRecord.objects.filter(record=Record.objects.get(pk=record_id))
        self.context['owners'] = owners
        checked_records = CheckedRecord.objects.filter(record=Record.objects.get(pk=record_id))
        adviser_checked = {'status': 'pending'}
        ktto_checked = {'status': 'pending'}
        rdco_checked = {'status': 'pending'}
        role_checked = False
        is_removable = False
        if request.user.role.pk > 3:
            is_removable = True
        for checked_record in checked_records:
            if checked_record.checked_by.role.id == 3:
                adviser_checked = {'status': checked_record.status, 'content': checked_record}
            if checked_record.checked_by.role.id == 4 or checked_record.checked_by.role.id == 7:
                ktto_checked = {'status': checked_record.status, 'content': checked_record}
            if checked_record.checked_by.role.id == 5:
                rdco_checked = {'status': checked_record.status, 'content': checked_record}
            if checked_record.checked_by.role.id == request.user.role.pk:
                role_checked = True
            if checked_record.status == 'declined':
                is_removable = True
        if UserRecord.objects.filter(user=request.user, record=Record.objects.get(pk=record_id)):
            is_owner = True
        self.context['adviser_checked'] = adviser_checked
        self.context['ktto_checked'] = ktto_checked
        self.context['rdco_checked'] = rdco_checked
        self.context['role_checked'] = role_checked
        self.context['record'] = Record.objects.get(pk=record_id)
        self.context['is_removable'] = is_removable
        return render(request, self.name, self.context)

    def post(self, request, record_id):
        if is_ajax(request=request):
            # removing record
            if request.POST.get('remove', 'false') == 'true':
                del_record = Record.objects.get(pk=record_id)
                del_record.abstract_file.delete()
                del_record.delete()
                return JsonResponse({'success': True})
            # get uploaded document data
            elif request.POST.get('get_document', 'false') == 'true':
                upload = Upload.objects.get(pk=request.POST.get('upload_id', 0))
                record = Record.objects.get(pk=request.POST.get('record_id', 0))
                record_upload = RecordUpload.objects.filter(upload=upload, record=record).first()
                checked_uploads = CheckedUpload.objects.filter(record_upload=record_upload).order_by('-date_checked')
                comments = []
                checked_bys = []
                checked_dates = []
                for checked_upload in checked_uploads:
                    comments.append(checked_upload.comment)
                    checked_bys.append(checked_upload.checked_by.username)
                    checked_dates.append(checked_upload.date_checked)
                if record_upload is None:
                    return JsonResponse({'success': False, 'doc-title': upload.name})
                else:
                    return JsonResponse({'success': True,
                                         'doc-title': record_upload.upload.name,
                                         'is-ip': record_upload.is_ip,
                                         'for-commercialization': record_upload.for_commercialization,
                                         'comments': comments,
                                         'checked_bys': checked_bys,
                                         'checked_dates': checked_dates,
                                         'record-upload-id': record_upload.pk})
            # POSTING COMMENTS
            elif request.POST.get('post_comment', 'false') == 'true':
                upload = Upload.objects.get(pk=request.POST.get('upload_id', 0))
                record = Record.objects.get(pk=request.POST.get('record_id', 0))
                comment = request.POST.get('comment', '')
                record_upload = RecordUpload.objects.filter(upload=upload, record=record).first()
                CheckedUpload(comment=comment, checked_by=request.user,
                              record_upload=record_upload).save()
                return JsonResponse({'success': True})
            else:
                return JsonResponse({'success': False})
        else:
            # approving or declining record
            if request.user.role.id > 2:
                checked_record_form = CheckedRecordForm(request.POST)
                if checked_record_form.is_valid():
                    checked_record = checked_record_form.save(commit=False)
                    checked_record.checked_by = request.user
                    checked_record.record = Record.objects.get(pk=record_id)
                    checked_record.status = request.POST.get('status')
                    checked_record.save()
                else:
                    print('invalid form')
                return redirect('records-declined-view', record_id)


class Add(View):
    name = 'records/add.html'
    author_roles = AuthorRole.objects.all()
    conference_levels = ConferenceLevel.objects.all()
    budget_types = BudgetType.objects.all()
    collaboration_types = CollaborationType.objects.all()
    record_types = RecordType.objects.all()
    record_form = forms.RecordForm()
    publication_form = forms.PublicationForm()
    uploads = Upload.objects.all()

    @method_decorator(authorized_roles(roles=['student', 'adviser', 'ktto', 'rdco', 'itso', 'tbi']))
    @method_decorator(login_required(login_url='/'))
    def get(self, request):
        context = {
            'author_roles': self.author_roles,
            'conference_levels': self.conference_levels,
            'budget_types': self.budget_types,
            'collaboration_types': self.collaboration_types,
            'record_types': self.record_types,
            'record_form': self.record_form,
            'publication_form': self.publication_form,
            'uploads': self.uploads,
            'site_key': settings.GOOGLE_RECAPTCHA_SITE_KEY,
            'test_form': settings.TEST_FORM,
        }
        return render(request, self.name, context)

    def post(self, request):
        error_messages = []
        record_form = forms.RecordForm(request.POST, request.FILES)
        if is_ajax(request=request):
            if request.POST.get("get_user_tags", 'false') == 'true':
                users = []
                advisers = []
                for user in User.objects.all():
                    users.append({'value': user.username, 'id': user.pk})
                for user in User.objects.filter(role__in=[3, 4, 5]):
                    advisers.append({'value': user.username, 'id': user.pk})
                return JsonResponse({'users': users, 'advisers': advisers})

        ''' reCAPTCHA validation '''
        recaptcha_response = request.POST.get('g-recaptcha-response')
        data = {
            'secret': settings.GOOGLE_RECAPTCHA_SECRET_KEY,
            'response': recaptcha_response
        }
        r = requests.post('https://www.google.com/recaptcha/api/siteverify', data=data)
        result = r.json()
        ''' End reCAPTCHA validation '''

        if record_form.is_valid() and not is_ajax(request=request) and (result['success'] or settings.TEST_FORM):
            record = record_form.save(commit=False)
            record.added_by = request.user
            file_is_valid = True
            file = record_form.cleaned_data.get('abstract_file', False)
            # check uploaded file size if valid
            if file and file.size > FILE_LENGTH:
                file_is_valid = False
            # saving record to database
            else:
                owners = json.loads(request.POST.get('owners-id'))
                adviser = json.loads(request.POST.get('adviser-id'))
                record.adviser = User.objects.get(pk=adviser[0]['id'])

                # Saving record code only if the role is student
                if request.user.role.pk == 2:
                    student = Student.objects.get(user=request.user)
                record.representative = f'{request.user.first_name} {request.user.last_name}'

                if file is not None:
                    record.abstract_filesize = record.abstract_file.size
                    record.abstract_filename = record.abstract_file.name
                    # upload_blob(settings.GS_BUCKET_NAME, record.abstract_file, record.abstract_file.name)
                    # record.abstract_file = None

                record.save()
                if request.user.role.pk == 2:
                    year = str(datetime.datetime.now().year)[2:]
                    serial = record.pk
                    college = student.course.department.college.code
                    department = student.course.department.code
                    record.code = f'{year}-{serial}-{college}-{department}-{student.user.last_name.upper()}'
                    record.save()
                # if the record type is proposal, the record will also be saved in the research group
                if record.record_type.pk == 1:
                    ResearchRecord(proposal=record).save()
                # documents search files check
                for upload in Upload.objects.all():
                    if record.record_type.pk == upload.record_type.pk:
                        if request.FILES.get(f'upload-{upload.pk}', None):
                            file = request.FILES.get(f'upload-{upload.pk}', None)
                            # upload_blob(settings.GS_BUCKET_NAME, file, file.name)
                            # RecordUpload(file=None, filename=file.name, record=record,
                            #         upload=upload, record_upload_status=RecordUploadStatus.objects.get(pk=1)).save()
                            RecordUpload(file=file, filename=file.name, record=record,
                                         upload=upload,
                                         record_upload_status=RecordUploadStatus.objects.get(pk=1)).save()
                for owner in owners:
                    UserRecord(user=User.objects.get(pk=int(owner['id'])), record=record).save()
            if record is not None and file_is_valid:
                publication_form = forms.PublicationForm(request.POST)
                if publication_form.is_valid():
                    publication = publication_form.save(commit=False)
                    publication.record = record
                    publication.save()
                author_names = request.POST.getlist('author_names[]', None)
                author_roles = request.POST.getlist('author_roles[]', None)
                conference_levels = request.POST.getlist('conference_levels[]', None)
                conference_titles = request.POST.getlist('conference_titles[]', None)
                conference_dates = request.POST.getlist('conference_dates[]', None)
                conference_venues = request.POST.getlist('conference_venues[]', None)

                budget_types = request.POST.getlist('budget_types[]', None)
                budget_allocations = request.POST.getlist('budget_allocations[]', None)
                funding_sources = request.POST.getlist('funding_sources[]', None)
                industries = request.POST.getlist('industries[]', None)
                institutions = request.POST.getlist('institutions[]', None)
                collaboration_types = request.POST.getlist('collaboration_types[]', None)
                for i, author_name in enumerate(author_names):
                    Author(name=author_name, author_role=AuthorRole.objects.get(pk=author_roles[i]),
                           record=record).save()

                for i, conference_title in enumerate(conference_titles):
                    Conference(title=conference_title,
                               conference_level=ConferenceLevel.objects.get(pk=conference_levels[i]),
                               date=conference_dates[i], venue=conference_venues[i], record=record).save()

                for i, budget_type in enumerate(budget_types):
                    Budget(budget_type=BudgetType.objects.get(pk=budget_types[i]),
                           budget_allocation=budget_allocations[i],
                           funding_source=funding_sources[i], record=record).save()
                for i, collaboration_type in enumerate(collaboration_types):
                    Collaboration(collaboration_type=CollaborationType.objects.get(pk=collaboration_types[i]),
                                  industry=industries[i], institution=institutions[i], record=record).save()
                messages.success(request, 'Record submitted!')
                # notification to adviser after adding new record
                newRecordAdded(request, request.user.id, record.adviser.id, record.id)
                return redirect('records-index')
            elif not file_is_valid:
                messages.error(request, 'The file size must not be more than 5MB')
            else:
                messages.error(request, 'A record with the same record information already exists')
        else:
            print(record_form.errors)
            messages.error(request, 'You must fill-in all the required fields')

        context = {
            'author_roles': self.author_roles,
            'conference_levels': self.conference_levels,
            'budget_types': self.budget_types,
            'collaboration_types': self.collaboration_types,
            'record_types': self.record_types,
            'record_form': record_form,
            'publication_form': self.publication_form,
            'uploads': self.uploads,
            'error_messages': error_messages,
        }
        return render(request, self.name, context)


class AddResearch(View):
    name = 'records/add_research.html'
    author_roles = AuthorRole.objects.all()
    conference_levels = ConferenceLevel.objects.all()
    budget_types = BudgetType.objects.all()
    collaboration_types = CollaborationType.objects.all()
    record_types = RecordType.objects.all()
    record_form = forms.RecordForm()
    publication_form = forms.PublicationForm()
    uploads = Upload.objects.all()

    @method_decorator(authorized_roles(roles=['student', 'adviser', 'ktto', 'rdco', 'itso', 'tbi']))
    @method_decorator(login_required(login_url='/'))
    def get(self, request, research_record_id):
        proposal_record = ResearchRecord.objects.get(pk=research_record_id).proposal
        context = {
            'author_roles': self.author_roles,
            'conference_levels': self.conference_levels,
            'budget_types': self.budget_types,
            'collaboration_types': self.collaboration_types,
            'record_types': self.record_types,
            'record_form': self.record_form,
            'publication_form': self.publication_form,
            'uploads': self.uploads,
            'proposal_record': proposal_record,
            'research_record_id': research_record_id,
        }
        return render(request, self.name, context)

    def post(self, request, research_record_id):
        error_messages = []
        record_form = forms.RecordForm(request.POST, request.FILES)
        proposal_record = ResearchRecord.objects.get(pk=research_record_id).proposal
        if is_ajax(request=request):
            if request.POST.get("get_user_tags", 'false') == 'true':
                users = []
                advisers = []
                for user in User.objects.all():
                    users.append({'value': user.username, 'id': user.pk})
                for user in User.objects.filter(role__in=[3, 4, 5]):
                    advisers.append({'value': user.username, 'id': user.pk})
                return JsonResponse({'users': users, 'advisers': advisers})
        if record_form.is_valid() and not is_ajax(request=request):
            record = record_form.save(commit=False)
            file_is_valid = True
            file = record_form.cleaned_data.get('abstract_file', False)
            # check uploaded file size if valid
            if file and file.size > FILE_LENGTH:
                file_is_valid = False
            # saving record to database
            else:
                owners = json.loads(request.POST.get('owners-id'))
                adviser = json.loads(request.POST.get('adviser-id'))
                record.adviser = User.objects.get(pk=adviser[0]['id'])
                record.record_type = RecordType.objects.get(pk=2)

                if file is not None:
                    record.abstract_filesize = record.abstract_file.size
                    record.abstract_filename = record.abstract_file.name
                    # upload_blob(settings.GS_BUCKET_NAME, record.abstract_file, record.abstract_file.name)
                    # record.abstract_file = None

                record.save()
                research_record = ResearchRecord.objects.get(pk=research_record_id)
                research_record.research = record
                research_record.save()
                # patent search files check
                for upload in Upload.objects.all():
                    if request.FILES.get(f'upload-{upload.pk}', None):
                        file = request.FILES.get(f'upload-{upload.pk}', None)
                        # upload_blob(settings.GS_BUCKET_NAME, file, file.name)
                        # RecordUpload(file=None, filename=file.name, record=record,
                        #                              upload=upload).save()
                        RecordUpload(file=file, filename=file.name, record=record, upload=upload).save()
                for owner in owners:
                    UserRecord(user=User.objects.get(pk=int(owner['id'])), record=record).save()
            if record is not None and file_is_valid:
                publication_form = forms.PublicationForm(request.POST)
                if publication_form.is_valid():
                    publication = publication_form.save(commit=False)
                    publication.record = record
                    publication.save()
                author_names = request.POST.getlist('author_names[]', None)
                author_roles = request.POST.getlist('author_roles[]', None)
                conference_levels = request.POST.getlist('conference_levels[]', None)
                conference_titles = request.POST.getlist('conference_titles[]', None)
                conference_dates = request.POST.getlist('conference_dates[]', None)
                conference_venues = request.POST.getlist('conference_venues[]', None)

                budget_types = request.POST.getlist('budget_types[]', None)
                budget_allocations = request.POST.getlist('budget_allocations[]', None)
                funding_sources = request.POST.getlist('funding_sources[]', None)
                industries = request.POST.getlist('industries[]', None)
                institutions = request.POST.getlist('institutions[]', None)
                collaboration_types = request.POST.getlist('collaboration_types[]', None)
                for i, author_name in enumerate(author_names):
                    Author(name=author_name, author_role=AuthorRole.objects.get(pk=author_roles[i]),
                           record=record).save()

                for i, conference_title in enumerate(conference_titles):
                    Conference(title=conference_title,
                               conference_level=ConferenceLevel.objects.get(pk=conference_levels[i]),
                               date=conference_dates[i], venue=conference_venues[i], record=record).save()

                for i, budget_type in enumerate(budget_types):
                    Budget(budget_type=BudgetType.objects.get(pk=budget_types[i]),
                           budget_allocation=budget_allocations[i],
                           funding_source=funding_sources[i], record=record).save()
                for i, collaboration_type in enumerate(collaboration_types):
                    Collaboration(collaboration_type=CollaborationType.objects.get(pk=collaboration_types[i]),
                                  industry=industries[i], institution=institutions[i], record=record).save()
                newRecordAdded(request, request.user.id, record.adviser.id, record.id)
                return redirect('records-index')
            elif not file_is_valid:
                error = {'title': 'Unable to save record',
                         'body': 'The file cannot be more than 5 MB'}
                error_messages.append(error)
            else:
                error = {'title': 'Unable to save record',
                         'body': 'A record with the same record information already exists'}
                error_messages.append(error)
        else:
            error_messages.append({'title': 'Unable to save record',
                                   'body': 'Some fields contains invalid values while trying to save the record'})
        context = {
            'author_roles': self.author_roles,
            'conference_levels': self.conference_levels,
            'budget_types': self.budget_types,
            'collaboration_types': self.collaboration_types,
            'record_form': record_form,
            'publication_form': self.publication_form,
            'proposal_record': proposal_record,
            'research_record_id': research_record_id,
            'error_messages': error_messages,
        }
        return render(request, self.name, context)


class Edit(View):
    name = 'records/edit.html'
    author_roles = AuthorRole.objects.all()
    conference_levels = ConferenceLevel.objects.all()
    budget_types = BudgetType.objects.all()
    collaboration_types = CollaborationType.objects.all()
    record_types = RecordType.objects.all()
    # record_form = forms.RecordForm()
    record_form = forms.EditRecordForm()
    publication_form = forms.PublicationForm()
    uploads = Upload.objects.all()

    @method_decorator(authorized_roles(roles=['student', 'adviser', 'ktto', 'rdco', 'itso', 'tbi']))
    @method_decorator(login_required(login_url='/'))
    def get(self, request, record_id):
        record = Record.objects.get(pk=record_id)
        authors = Author.objects.filter(record=record)
        conferences = Conference.objects.filter(record=record)
        budgets = Budget.objects.filter(record=record)
        collaborations = Collaboration.objects.filter(record=record)
        # record_form = forms.RecordForm(instance=record)
        record_form = forms.EditRecordForm(instance=record)
        publication_form = forms.PublicationForm(instance=Publication.objects.get(record=record))
        publication_name = Publication.objects.get(record=record).name
        record_uploads = record.recordupload_set.all()
        context = {
            'author_roles': self.author_roles,
            'conference_levels': self.conference_levels,
            'budget_types': self.budget_types,
            'collaboration_types': self.collaboration_types,
            'record_types': self.record_types,
            'record_form': record_form,
            'publication_form': publication_form,
            'publication_name': publication_name,
            'record': record,
            'authors': authors,
            'conferences': conferences,
            'budgets': budgets,
            'collaborations': collaborations,
            'uploads': self.uploads,
            'recorduploads': record_uploads,

            'filename': record.abstract_filename,
        }
        return render(request, self.name, context)

    def post(self, request, record_id):
        error_messages = []
        record_instance = Record.objects.get(pk=record_id)
        # record_form = forms.RecordForm(request.POST, request.FILES, instance=Record.objects.get(pk=record_id))
        record_form = forms.EditRecordForm(request.POST, request.FILES, instance=Record.objects.get(pk=record_id))
        if is_ajax(request=request):
            if request.POST.get("get_user_tags", 'false') == 'true':
                users = []
                for user in User.objects.all():
                    users.append({'value': user.username, 'id': user.pk})
                return JsonResponse({'users': users})

        if record_form.is_valid():
            record = record_form.save(commit=False)
            if record is None:
                record = record_instance
            record.record_type = record_instance.record_type
            file_is_valid = True
            file = record_form.cleaned_data.get('abstract_file', False)
            # check abstract file size if valid
            if file and file.size > FILE_LENGTH:
                file_is_valid = False

            # saving record to database
            else:
                if file and file != record_instance.abstract_filename:
                    print(file, ' != ', record_instance.abstract_filename)
                    # delete_blob(settings.GS_BUCKET_NAME, record_instance.abstract_filename)
                    record.abstract_filesize = record.abstract_file.size
                    record.abstract_filename = record.abstract_file.name
                    # upload_blob(settings.GS_BUCKET_NAME, record.abstract_file, record.abstract_file.name)
                    # record.abstract_file = None

                record.save()
                # documents search files check
                for upload in Upload.objects.all():
                    if request.FILES.get(f'upload-{upload.pk}', None):
                        record_upload = RecordUpload.objects.filter(record=record, upload=upload).first()
                        file = request.FILES.get(f'upload-{upload.pk}', None)

                        if record_upload is not None:
                            # if file and file != record_upload.filename:
                            #     print(file, ' != ', record_upload.filename)
                            #     delete_blob(settings.GS_BUCKET_NAME, record_upload.filename)
                            #     upload_blob(settings.GS_BUCKET_NAME, file, file.name)
                            if record_upload.record_upload_status.pk not in [2, 3, 5]:
                                record_upload.file = file
                                # record_upload.file = None
                                record_upload.filename = file.name
                                record_upload.save()
                            else:
                                messages.error(request, 'Cannot be updated, document has been processed')
                        else:
                            # upload_blob(settings.GS_BUCKET_NAME, file, file.name)
                            # RecordUpload(file=None, filename=file.name, record=record,
                            #                          upload=upload, record_upload_status=RecordUploadStatus.objects.get(pk=1)).save()
                            RecordUpload(file=file, filename=file.name, record=record,
                                         upload=upload,
                                         record_upload_status=RecordUploadStatus.objects.get(pk=1)).save()

            if record is not None and file_is_valid:
                publication_form = forms.PublicationForm(request.POST, instance=Publication.objects.get(record=record))
                if publication_form.is_valid():
                    publication = publication_form.save(commit=False)
                    publication.record = record
                    publication.save()
                author_names = request.POST.getlist('author_names[]', None)
                author_roles = request.POST.getlist('author_roles[]', None)
                conference_levels = request.POST.getlist('conference_levels[]', None)
                conference_titles = request.POST.getlist('conference_titles[]', None)
                conference_dates = request.POST.getlist('conference_dates[]', None)
                conference_venues = request.POST.getlist('conference_venues[]', None)

                budget_types = request.POST.getlist('budget_types[]', None)
                budget_allocations = request.POST.getlist('budget_allocations[]', None)
                funding_sources = request.POST.getlist('funding_sources[]', None)
                industries = request.POST.getlist('industries[]', None)
                institutions = request.POST.getlist('institutions[]', None)
                collaboration_types = request.POST.getlist('collaboration_types[]', None)

                Author.objects.filter(record=record).delete()
                for i, author_name in enumerate(author_names):
                    Author(name=author_name, author_role=AuthorRole.objects.get(pk=author_roles[i]),
                           record=record).save()

                Conference.objects.filter(record=record).delete()
                for i, conference_title in enumerate(conference_titles):
                    Conference(title=conference_title,
                               conference_level=ConferenceLevel.objects.get(pk=conference_levels[i]),
                               date=conference_dates[i], venue=conference_venues[i], record=record).save()

                Budget.objects.filter(record=record).delete()
                for i, budget_type in enumerate(budget_types):
                    Budget(budget_type=BudgetType.objects.get(pk=budget_types[i]),
                           budget_allocation=budget_allocations[i],
                           funding_source=funding_sources[i], record=record).save()
                Collaboration.objects.filter(record=record).delete()
                for i, collaboration_type in enumerate(collaboration_types):
                    Collaboration(collaboration_type=CollaborationType.objects.get(pk=collaboration_types[i]),
                                  industry=industries[i], institution=institutions[i], record=record).save()
                newRecordAdded(request, request.user.id, record.adviser.id, record.id)
                return JsonResponse({'success': 1})
            elif not file_is_valid:
                error = {'title': 'Unable to save record',
                         'body': 'The file cannot be more than 5 MB'}
                error_messages.append(error)
            else:
                error = {'title': 'Unable to save record',
                         'body': 'A record with the same record information already exists'}
                error_messages.append(error)
        else:
            error_messages.append({'title': 'Unable to save record',
                                   'body': 'Some fields contains invalid values while trying to save the record'})
        context = {
            'author_roles': self.author_roles,
            'conference_levels': self.conference_levels,
            'budget_types': self.budget_types,
            'collaboration_types': self.collaboration_types,
            'record_form': record_form,
            'record': record_instance,
            'publication_form': self.publication_form,
            'error_messages': error_messages,
        }
        return JsonResponse({'success': 0})


class ParseExcel(View):
    def post(self, request):
        row_count = 5
        count = 0
        error_count = 0
        now = datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        logs = now + '\n'
        try:
            excel_file = request.FILES['file']
            data = {}
            if str(excel_file).split('.')[-1] == 'xls':
                data = xls_get(excel_file, column_limit=50)
            elif str(excel_file).split('.')[-1] == 'xlsx':
                data = xlsx_get(excel_file, column_limit=50)
            data = data['ResearchProductivity'][6:][0:]
            for d in data:
                row_count += 1
                if d[0] != 'end of records':
                    representative = d[0]
                    title = d[1]
                    year_accomplished = d[2]
                    classification = 1
                    psced_classification = d[5]
                    if not d[3]:
                        classification = 2
                    conference_level = 1
                    conference_title = d[9]
                    conference_date = d[14]
                    conference_venue = d[15]
                    if d[11]:
                        conference_level = 2
                    elif d[12]:
                        conference_level = 3
                    elif d[13]:
                        conference_level = 4
                    record_len = len(Record.objects.filter(title=title, year_accomplished=year_accomplished,
                                                           classification=Classification.objects.get(pk=classification),
                                                           psced_classification=PSCEDClassification.objects.get(
                                                               pk=psced_classification)))
                    if record_len == 0:
                        record = Record(title=title, year_accomplished=year_accomplished,
                                        classification=Classification.objects.get(pk=classification),
                                        psced_classification=PSCEDClassification.objects.get(pk=psced_classification),
                                        record_type=RecordType.objects.get(pk=3), representative=representative)
                        record.save()
                        UserRecord(record=record, user=request.user).save()
                    else:
                        logs += f'\nDuplicate entry on row "{row_count}"'
                        error_count += 1
                        continue
                    Conference(title=conference_title,
                               conference_level=ConferenceLevel.objects.get(pk=conference_level),
                               date=conference_date, venue=conference_venue, record=record).save()
                    if d[16]:
                        publication_name = d[23]
                        sn_list = "".join(d[24].split()).split(',')
                        isbn = ''
                        issn = ''
                        isi = ''
                        for sn in sn_list:
                            if sn.upper().find('ISBN:') >= 0:
                                isbn = sn.replace('ISBN:', '')
                            elif sn.upper().find('ISSN:') >= 0:
                                issn = sn.replace('ISSN:', '')
                            elif sn.upper().find('ISI:') >= 0:
                                isi = sn.replace('ISI:', '')
                        publication_level = 1
                        if d[20]:
                            publication_level = 2
                        elif d[21]:
                            publication_level = 3
                        elif d[22]:
                            publication_level = 4
                        year_published = d[18]
                        Publication(name=publication_name, isbn=isbn, issn=issn, isi=isi,
                                    publication_level=PublicationLevel.objects.get(pk=publication_level),
                                    year_published=year_published, record=record).save()
                    else:
                        Publication(record=record).save()
                    if d[25]:
                        budget_type = 1
                        budget_allocation = d[30]
                        funding_source = d[31]
                        if d[28]:
                            budget_type = 2
                        elif d[20]:
                            budget_type = 3
                        Budget(budget_type=BudgetType.objects.get(pk=budget_type),
                               budget_allocation=budget_allocation,
                               funding_source=funding_source, record=record).save()
                    if d[32]:
                        industry = d[34]
                        institution = d[35]
                        collaboration_type = 1
                        if len(d) >= 38:
                            if d[37]:
                                collaboration_type = 2

                        elif len(d) >= 39:
                            if d[38]:
                                collaboration_type = 3
                        Collaboration(collaboration_type=CollaborationType.objects.get(pk=collaboration_type),
                                      industry=industry, institution=institution, record=record).save()
                    count += 1
                else:
                    break
            messages.success(request, f'{count} records imported!')
            messages.error(request,
                           f'{error_count} records contains errors and cannot be imported. See Upload page for the logs...')
            request.session[
                'logs'] = logs + f'\nTotal records found: {row_count - 6}, Success: {count}, Errors: {error_count}'
        except (MultiValueDictKeyError, KeyError, ValueError, OSError):
            messages.error(request, "Some rows have invalid values")
            print('Multivaluedictkeyerror/KeyError/ValueError/OSError')
        except (DataError, ValidationError):
            messages.error(request, "The form is invalid")
            print('DataError/ValidationError')
        return redirect('records-index')


@authorized_roles(roles=['adviser', 'ktto', 'rdco', 'itso', 'tbi'])
def download_format(request):
    fl_path = '/media'
    filename = 'data.xlsx'
    fl = open('media/data.xlsx', 'rb')
    mime_type = mimetypes.guess_type(fl_path)
    response = HttpResponse(fl, content_type=mime_type)
    response['Content-Disposition'] = "attachment; filename=%s" % filename
    return response


@authorized_roles(roles=['student', 'adviser', 'ktto', 'rdco', 'itso', 'tbi'])
def download_abstract(request, record_id):
    record = Record.objects.get(pk=record_id)
    # filename = record.abstract_file.name.split('/')[-1]
    filename = record.abstract_filename
    response = HttpResponse(record.abstract_file, content_type='text/plain')
    response['Content-Disposition'] = 'attachment; filename=%s' % filename
    return response

    # download abstract from google cloud storage
    # record = Record.objects.get(pk=record_id)
    # # source_blob_name = 'abstract/'+record.abstract_filename
    # source_blob_name = record.abstract_filename
    # link = download_blob(settings.GS_BUCKET_NAME, source_blob_name)
    # return HttpResponseRedirect(link)


# documents in upload tab
@authorized_roles(roles=['student', 'adviser', 'ktto', 'rdco', 'itso', 'tbi'])
def download_document(request, record_upload_id):
    record_upload = RecordUpload.objects.get(pk=record_upload_id)
    # filename = record_upload.file.name.split('/')[-1]
    filename = record_upload.filename
    response = HttpResponse(record_upload.file, content_type='text/plain')
    response['Content-Disposition'] = 'attachment; filename=%s' % filename
    return response

    # download document from google cloud storage
    # record_upload = RecordUpload.objects.get(pk=record_upload_id)
    # # source_blob_name = 'abstract/'+record.abstract_filename
    # source_blob_name = record_upload.filename
    # link = download_blob(settings.GS_BUCKET_NAME, source_blob_name)
    # return HttpResponseRedirect(link)


# table view of all my records
class MyRecordsView(View):
    template_name = 'records/profile/my_records.html'

    @method_decorator(login_required(login_url='/'))
    @method_decorator(authorized_roles(roles=['student', 'adviser', 'ktto', 'rdco', 'itso', 'tbi']))
    def get(self, request):
        return render(request, self.template_name)

    def post(self, request):
        user_records = UserRecord.objects.filter(user=request.user)
        data = []
        for user_record in user_records:
            record = Record.objects.get(title=user_record.record)
            adviser_checked = f'<div class="badge badge-secondary">pending</div>'
            ktto_checked = f'<div class="badge badge-secondary">pending</div>'
            rdco_checked = f'<div class="badge badge-secondary">pending</div>'
            for checked_record in CheckedRecord.objects.filter(record=user_record.record):
                if checked_record.status == 'approved':
                    badge = 'success'
                elif checked_record.status == 'declined':
                    badge = 'danger'
                else:
                    badge = 'secondary'
                record_status = f'<div class="badge badge-{badge}">{checked_record.status}</div>'
                if checked_record.checked_by.role.pk == 3:
                    adviser_checked = record_status
                elif checked_record.checked_by.role.pk == 4 or checked_record.checked_by.role.id == 7:
                    ktto_checked = record_status
                elif checked_record.checked_by.role.pk == 5:
                    rdco_checked = record_status
            if record.is_marked == False:
                data.append([
                    record.pk,
                    '<a href="/record/myrecords/' + str(
                        record.pk) + '">' + record.title + '</a>',
                    adviser_checked,
                    ktto_checked,
                    rdco_checked,
                ])
            elif record.is_marked == True:
                data.append([
                    record.pk,
                    record.title + ' <i class="fa fa-ban" aria-hidden="true" title="Marked for deletion"></i>',
                    adviser_checked,
                    ktto_checked,
                    rdco_checked,
                ])
        return JsonResponse({"data": data})


# Pending records table
class PendingRecordsView(View):
    template_name = 'records/profile/pending_records.html'

    @method_decorator(login_required(login_url='/'))
    @method_decorator(authorized_roles(roles=['student', 'adviser', 'ktto', 'rdco', 'tbi']))
    def get(self, request):
        return render(request, self.template_name)

    def post(self, request):
        if request.user.role.id == 3:
            adviser_exclude = CheckedRecord.objects.select_related('record').all()
            adviser_pending_records = Record.objects.filter(adviser=request.user.pk).exclude(
                pk__in=Subquery(adviser_exclude.values('record').distinct())).values('pk', 'title')
            tuples_adviser_pending_records = [tuple(a.values()) for a in adviser_pending_records]

            data = []
            for row in tuples_adviser_pending_records:
                data.append([
                    row[0],
                    '<a href="/record/pending/' + str(row[0]) + '">' + row[1] + '</a>',
                ])
        elif request.user.role.id == 4 or request.user.role.id == 7:
            ktto_exclude = CheckedRecord.objects.select_related('record').filter(
                Q(checked_by__in=Subquery(User.objects.filter(role=4).values('pk'))) | Q(
                    checked_by__in=Subquery(User.objects.filter(role=7).values('pk'))))
            ktto_include = CheckedRecord.objects.select_related('record').filter(status='approved',
                                                                                 checked_by__in=Subquery(
                                                                                     User.objects.filter(role=3).values(
                                                                                         'pk')))
            ktto_pending_records = Record.objects.filter(pk__in=Subquery(ktto_include.values('record'))).exclude(
                pk__in=Subquery(ktto_exclude.values('record'))).values('pk', 'title', 'is_marked')
            tuples_ktto_pending_records = [tuple(k.values()) for k in ktto_pending_records]

            data = []
            for row in tuples_ktto_pending_records:
                if row[2] == False:
                    data.append([
                        row[0],
                        f'<a href="/record/pending/{row[0]}">{row[1]}</a>'
                    ])
                else:
                    data.append([
                        row[0],
                        row[1] + ' <i class="fa fa-ban" aria-hidden="true" title="Marked for deletion"></i>'
                    ])
        elif request.user.role.id == 5:
            rdco_exclude = CheckedRecord.objects.select_related('record').filter(
                checked_by__in=Subquery(User.objects.filter(role=5).values('pk')))
            rdco_include = CheckedRecord.objects.select_related('record').filter(
                Q(checked_by__in=Subquery(User.objects.filter(role=4).values('pk'))) | Q(
                    checked_by__in=Subquery(User.objects.filter(role=7).values('pk'))), status='approved')
            rdco_pending_records = Record.objects.filter(pk__in=Subquery(rdco_include.values('record'))).exclude(
                pk__in=Subquery(rdco_exclude.values('record'))).values('pk', 'title', 'is_marked')
            tuples_rdco_pending_records = [tuple(r.values()) for r in rdco_pending_records]

            data = []
            for row in tuples_rdco_pending_records:
                if row[2] == False:
                    data.append([
                        row[0],
                        f'<a href="/record/pending/{row[0]}">{row[1]}</a>'
                    ])
                else:
                    data.append([
                        row[0],
                        row[1] + ' <i class="fa fa-ban" aria-hidden="true" title="Marked for deletion"></i>'
                    ])
        return JsonResponse({"data": data})


class ApprovedRecordsView(View):
    template_name = 'records/profile/approved_records.html'

    @method_decorator(login_required(login_url='/'))
    @method_decorator(authorized_roles(roles=['student', 'adviser', 'ktto', 'rdco', 'tbi']))
    def get(self, request):
        return render(request, self.template_name)

    def post(self, request):
        checked_records = CheckedRecord.objects.filter(checked_by=request.user, status='approved')
        data = []
        for checked_record in checked_records:
            data.append([
                checked_record.record.pk,
                f'<a href="/record/approved/{checked_record.record.pk}">{checked_record.record.title}</a>'
            ])
        return JsonResponse({'data': data})


class DeclinedRecordsView(View):
    template_name = 'records/profile/declined_records.html'

    @method_decorator(login_required(login_url='/'))
    @method_decorator(authorized_roles(roles=['student', 'adviser', 'ktto', 'rdco', 'tbi']))
    def get(self, request):
        return render(request, self.template_name)

    def post(self, request):
        checked_records = CheckedRecord.objects.filter(checked_by=request.user, status='declined')
        data = []
        for checked_record in checked_records:
            data.append([
                checked_record.record.pk,
                f'<a href="/record/declined/{checked_record.record.pk}">{checked_record.record.title}</a>'
            ])
        return JsonResponse({'data': data})


class Dashboard(View):
    name = 'records/dashboard.html'

    @method_decorator(login_required(login_url='/'))
    @method_decorator(authorized_roles(roles=['ktto', 'rdco', 'itso', 'tbi']))
    def get(self, request):
        return render(request, self.name)

    def post(self, request):
        if is_ajax(request=request):
            checked_records = CheckedRecord.objects.filter(status='approved', checked_by__in=Subquery(
                User.objects.filter(role=5).values('pk')))
            records = Record.objects.filter(pk__in=Subquery(checked_records.values('record_id')))
            # graphs
            if request.POST.get('graphs'):
                basic_count = records.filter(classification=1).count()
                applied_count = records.filter(classification=2).count()
                psced_count = []
                records_per_year_count = []
                psced_per_year_count = []
                adviser_pending_count = []
                psced_classifications = PSCEDClassification.objects.all()
                records_per_year = records.values('year_accomplished').annotate(
                    year_count=Count('year_accomplished')).order_by('year_accomplished')[:10]
                for psced in psced_classifications:
                    psced_count.append({'name': psced.name, 'count': records.filter(
                        psced_classification=PSCEDClassification.objects.get(pk=psced.id)).count()})
                for record_per_year in records_per_year:
                    records_per_year_count.append(
                        {'year': record_per_year['year_accomplished'], 'count': record_per_year['year_count']})

                # NUMBER OF CLASSIFICATIONS PER YEAR
                # year_count = records.values('year_accomplished').distinct().annotate(psced_count=Count('psced_classification', distinct=True)).order_by('year_accomplished')
                # Convert all year_count values into a list of tuples
                # tuples_year_count = [tuple(d.values()) for d in year_count]
                # for row in tuples_year_count:
                #    psced_per_year_count.append({'year': row[0], 'psced_count': row[1]})
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT year_accomplished, COUNT(year_accomplished) AS year_count FROM (SELECT DISTINCT year_accomplished, psced_classification_id FROM (select year_accomplished, psced_classification_id from records_record inner join records_checkedrecord on records_record.id=record_id inner join accounts_user on records_checkedrecord.checked_by_id=accounts_user.id where accounts_user.role_id=5 and records_checkedrecord.status='approved') as recordtbl) as tbl GROUP BY year_accomplished")
                    rows = cursor.fetchall()
                    print(rows)
                    for row in rows:
                        psced_per_year_count.append({'year': row[0], 'psced_count': row[1]})

                # Pending Adviser
                # adviser_exclude = CheckedRecord.objects.select_related('record').all()
                # adviser_pending = Record.objects.exclude(pk__in=Subquery(adviser_exclude.values('record').distinct())).values('pk', 'title')
                # adviser_pending_count = adviser_pending.count()
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"select records_record.id, records_record.title, records_checkedrecord.checked_by_id from records_record left join records_checkedrecord on records_record.id = records_checkedrecord.record_id where checked_by_id is null")
                    rows = cursor.fetchall()
                    print(rows)
                    adviser_pending_count = len(rows)

                # Pending KTTO
                # ktto_exclude = CheckedRecord.objects.select_related('record').filter(Q(checked_by__in=Subquery(User.objects.filter(role=4).values('pk'))) | Q(checked_by__in=Subquery(User.objects.filter(role=7).values('pk'))))
                # ktto_include = CheckedRecord.objects.select_related('record').filter(status='approved', checked_by__in=Subquery(User.objects.filter(role=3).values('pk')))
                # ktto_pending = Record.objects.filter(pk__in=Subquery(ktto_include.values('record'))).exclude(pk__in=Subquery(ktto_exclude.values('record'))).values('pk', 'title')         
                # ktto_pending_count = ktto_pending.count()
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT records_record.id, records_record.title FROM records_record INNER JOIN records_checkedrecord ON records_record.id = records_checkedrecord.record_id INNER JOIN accounts_user ON records_checkedrecord.checked_by_id = accounts_user.id WHERE accounts_user.role_id = 3 AND records_checkedrecord.status = 'approved' AND records_record.id NOT IN (SELECT records_checkedrecord.record_id FROM records_checkedrecord INNER JOIN accounts_user ON records_checkedrecord.checked_by_id = accounts_user.id WHERE accounts_user.role_id = 4 or accounts_user.role_id = 7)")
                    rows = cursor.fetchall()
                    print(rows)
                    ktto_pending_count = len(rows)

                # Pending RDCO
                # rdco_exclude = CheckedRecord.objects.select_related('record').filter(checked_by=Subquery(User.objects.filter(role=5).values('pk')))
                # rdco_include = CheckedRecord.objects.select_related('record').filter(checked_by__in=Subquery(User.objects.filter(role=4).values('pk')), status='approved')
                # rdco_pending = Record.objects.filter(pk__in=Subquery(rdco_include.values('record'))).exclude(pk__in=Subquery(rdco_exclude.values('record'))).values('pk', 'title')
                # print(rdco_pending)
                # rdco_pending_count = rdco_pending.count()
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT records_record.id, records_record.title FROM records_record INNER JOIN records_checkedrecord ON records_record.id = records_checkedrecord.record_id INNER JOIN accounts_user ON records_checkedrecord.checked_by_id = accounts_user.id WHERE accounts_user.role_id = 4 AND records_checkedrecord.status = 'approved' AND records_record.id NOT IN (SELECT records_checkedrecord.record_id FROM records_checkedrecord INNER JOIN accounts_user ON records_checkedrecord.checked_by_id = accounts_user.id WHERE accounts_user.role_id = 5)")
                    rows = cursor.fetchall()
                    rdco_pending_count = len(rows)
                    print(rows)
                record_uploads = RecordUpload.objects.all()

                def get_doc_counts(docs):
                    patent_count = 0
                    utility_model_count = 0
                    industrial_design_count = 0
                    trademark_count = 0
                    copyright_count = 0
                    for data in docs:
                        if data.upload.name == 'Patent':
                            patent_count += 1
                        if data.upload.name == 'Utility Model':
                            utility_model_count += 1
                        if data.upload.name == 'Industrial Design':
                            industrial_design_count += 1
                        if data.upload.name == 'Trademark':
                            trademark_count += 1
                        if data.upload.name == 'Copyright':
                            copyright_count += 1
                    return [patent_count, utility_model_count, industrial_design_count, trademark_count,
                            copyright_count]

                for_application = get_doc_counts(
                    record_uploads.filter(record_upload_status=RecordUploadStatus.objects.get(pk=1)))
                reviewed = get_doc_counts(
                    record_uploads.filter(record_upload_status=RecordUploadStatus.objects.get(pk=2)))
                filed = get_doc_counts(record_uploads.filter(record_upload_status=RecordUploadStatus.objects.get(pk=3)))
                approved = get_doc_counts(
                    record_uploads.filter(record_upload_status=RecordUploadStatus.objects.get(pk=4)))
                disapproved = get_doc_counts(
                    record_uploads.filter(record_upload_status=RecordUploadStatus.objects.get(pk=5)))
                return JsonResponse({'success': True, 'basic': basic_count, 'applied': applied_count,
                                     'psced_count': psced_count, 'records_per_year_count': records_per_year_count,
                                     'psced_per_year_count': psced_per_year_count,
                                     'adviser_pending_count': adviser_pending_count,
                                     'ktto_pending_count': ktto_pending_count, 'rdco_pending_count': rdco_pending_count,
                                     'for_application': for_application, 'reviewed': reviewed, 'filed': filed,
                                     'approved': approved, 'disapproved': disapproved})


class LogsView(View):
    name = 'records/dashboard/logs_view.html'

    @method_decorator(authorized_roles(roles=['ktto', 'rdco', 'tbi', 'itso']))
    @method_decorator(login_required(login_url='/'))
    def get(self, request):
        return render(request, self.name)

    def post(self, request):
        if is_ajax(request=request):
            data = []
            logs = Log.objects.all()
            for log in logs:
                data.append([log.pk, log.action, log.user.username, log.date_created.strftime("%Y-%m-%d %H:%M:%S")])
            return JsonResponse({'data': data})


class DashboardLogsRecordView(View):
    name = 'records/dashboard/logs_view_record.html'
    author_roles = AuthorRole.objects.all()
    classifications = Classification.objects.all()
    psced_classifications = PSCEDClassification.objects.all().order_by('name')
    conference_levels = ConferenceLevel.objects.all()
    budget_types = BudgetType.objects.all()
    collaboration_types = CollaborationType.objects.all()
    publication_levels = PublicationLevel.objects.all()
    uploads = Upload.objects.all()
    checked_record_form = CheckedRecordForm()
    context = {
        'author_roles': author_roles,
        'classifications': classifications,
        'psced_classifications': psced_classifications,
        'conference_levels': conference_levels,
        'budget_types': budget_types,
        'collaboration_types': collaboration_types,
        'publication_levels': publication_levels,
        'uploads': uploads,
        'checked_record_form': checked_record_form,
        'is_owner': True,
    }

    @method_decorator(login_required(login_url='/'))
    @method_decorator(authorized_record_user())
    def get(self, request, record_id):
        owners = UserRecord.objects.filter(record=Record.objects.get(pk=record_id))
        self.context['owners'] = owners
        checked_records = CheckedRecord.objects.filter(record=Record.objects.get(pk=record_id))
        adviser_checked = {'status': 'pending'}
        ktto_checked = {'status': 'pending'}
        rdco_checked = {'status': 'pending'}
        role_checked = False
        record = Record.objects.get(pk=record_id)
        research_record = ResearchRecord.objects.filter(Q(proposal=record) | Q(research=record)).first()
        for checked_record in checked_records:
            if checked_record.checked_by.role.id == 3:
                adviser_checked = {'status': checked_record.status, 'content': checked_record}
            if checked_record.checked_by.role.id == 4 or checked_record.checked_by.role.id == 7:
                ktto_checked = {'status': checked_record.status, 'content': checked_record}
            if checked_record.checked_by.role.id == 5:
                rdco_checked = {'status': checked_record.status, 'content': checked_record}
            if checked_record.checked_by.role.id == request.user.role.pk:
                role_checked = True
        self.context['adviser_checked'] = adviser_checked
        self.context['ktto_checked'] = ktto_checked
        self.context['rdco_checked'] = rdco_checked
        self.context['role_checked'] = role_checked
        self.context['record'] = record
        self.context['is_removable'] = True
        self.context['research_record'] = research_record
        return render(request, self.name, self.context)

    def post(self, request, record_id):
        if is_ajax(request=request):
            # removing record
            if request.POST.get('remove', 'false') == 'true':
                del_record = Record.objects.get(pk=record_id)
                del_record.abstract_file.delete()
                del_record_uploads = RecordUpload.objects.filter(record=del_record)
                for del_record_upload in del_record_uploads:
                    del_record_upload.file.delete()
                del_record.delete()
                return JsonResponse({'success': True})
            # updating record tags
            elif request.POST.get('tags_update', 'false') == 'true':
                return JsonResponse(update_record_tags(request, record_id))
            # get uploaded document data
            elif request.POST.get('get_document', 'false') == 'true':
                upload = Upload.objects.get(pk=request.POST.get('upload_id', 0))
                record = Record.objects.get(pk=request.POST.get('record_id', 0))
                record_upload = RecordUpload.objects.filter(upload=upload, record=record).first()
                checked_uploads = CheckedUpload.objects.filter(record_upload=record_upload).order_by('-date_checked')
                comments = []
                checked_bys = []
                checked_dates = []
                for checked_upload in checked_uploads:
                    comments.append(checked_upload.comment)
                    checked_bys.append(checked_upload.checked_by.username)
                    checked_dates.append(checked_upload.date_checked)
                if record_upload is None:
                    return JsonResponse({'success': False, 'doc-title': upload.name})
                else:
                    return JsonResponse({'success': True,
                                         'doc-title': record_upload.upload.name,
                                         'doc-status': record_upload.record_upload_status.name,
                                         'is-ip': record_upload.is_ip,
                                         'for-commercialization': record_upload.for_commercialization,
                                         'comments': comments,
                                         'checked_bys': checked_bys,
                                         'checked_dates': checked_dates,
                                         'record-upload-id': record_upload.pk})
            # POSTING COMMENTS
            elif request.POST.get('post_comment', 'false') == 'true':
                upload = Upload.objects.get(pk=request.POST.get('upload_id', 0))
                record = Record.objects.get(pk=request.POST.get('record_id', 0))
                comment = request.POST.get('comment', '')
                record_upload = RecordUpload.objects.filter(upload=upload, record=record).first()
                CheckedUpload(comment=comment, checked_by=request.user, record_upload=record_upload).save()
                return JsonResponse({'success': True})
            else:
                return JsonResponse({'success': False})
        else:
            # approving or declining record
            if request.user.role.id > 2:
                checked_record_form = CheckedRecordForm(request.POST)
                if checked_record_form.is_valid():
                    checked_record = checked_record_form.save(commit=False)
                    checked_record.checked_by = request.user
                    checked_record.record = Record.objects.get(pk=record_id)
                    checked_record.status = request.POST.get('status')
                    checked_record.save()
                else:
                    print('invalid form')
                return redirect('records-view', record_id)


# dashboard manage records table
class ViewManageRecords(View):
    name = 'records/dashboard/manage_records.html'

    @method_decorator(authorized_roles(roles=['adviser', 'ktto', 'rdco', 'tbi', 'itso']))
    @method_decorator(login_required(login_url='/'))
    def get(self, request):
        return render(request, self.name)

    def post(self, request):
        if is_ajax(request=request):
            records = Record.objects.all()
            data = []

            # filtering records
            if request.POST.get('is-filter', '0') == '1':
                is_ip = request.POST.get('is-ip', 0)
                commercialization = request.POST.get('for-commercialization', 0)
                community_ext = request.POST.get('community-ext', 0)
                no_tags = request.POST.get('no-tags', 0)
                record_publish_status = request.POST.get('record-publish-status', 0)
                if record_publish_status == '1':
                    checked_records = CheckedRecord.objects.filter(status='approved', checked_by__in=Subquery(
                        User.objects.filter(role=5).values('pk')))
                    records = records.filter(pk__in=Subquery(checked_records.values('record_id')))
                elif record_publish_status == '2':
                    checked_records = CheckedRecord.objects.filter(status='approved', checked_by__in=Subquery(
                        User.objects.filter(role=5).values('pk')))
                    records = records.exclude(pk__in=Subquery(checked_records.values('record_id')))
                if is_ip == '1':
                    records = records.filter(is_ip=True)
                if commercialization == '1':
                    records = records.filter(for_commercialization=True)
                if community_ext == '1':
                    records = records.filter(community_extension=True)
                if no_tags == '1':
                    records = records.filter(community_extension=False, is_ip=False, for_commercialization=False)

            # removing records
            elif request.POST.get('remove'):
                titles = request.POST.getlist('titles[]')
                for title_id in titles:
                    del_record = Record.objects.get(pk=int(title_id))
                    del_record.abstract_file.delete()
                    del_record.delete()
                return JsonResponse({'success': True})

            # Edit record code
            elif request.POST.get('edit-record-code', 'false') == 'true':
                record = Record.objects.get(pk=request.POST.get('record-id', None))
                record_code = request.POST.get('record-code', None)
                record.code = record_code
                record.save()

            for record in records:
                tags = ''
                if record.is_ip:
                    tags = f'<div class="badge badge-primary">IP</div>&nbsp;'
                if record.for_commercialization:
                    tags += f'<div class="badge badge-success">For commercialization</div>&nbsp;'
                if record.community_extension:
                    tags += f'<div class="badge badge-secondary">Community extension</div>&nbsp;'
                data.append([
                    '',
                    record.pk,
                    f'{record.code} <a href="#" onclick="editCode({record.pk},\'{record.code}\')"><i class="fa fa-pen fa-md"></i></a>',
                    f'<a href="/dashboard/manage/records/{record.pk}">{record.title}</a>',
                    record.record_type.name,
                    record.date_created.strftime("%Y-%m-%d %H:%M:%S"),
                    tags,
                ])

            return JsonResponse({'data': data})


# Dashboard manage record template
class DashboardManageRecord(View):
    name = 'records/dashboard/manage_view_record.html'
    author_roles = AuthorRole.objects.all()
    classifications = Classification.objects.all()
    psced_classifications = PSCEDClassification.objects.all().order_by('name')
    conference_levels = ConferenceLevel.objects.all()
    budget_types = BudgetType.objects.all()
    collaboration_types = CollaborationType.objects.all()
    publication_levels = PublicationLevel.objects.all()
    uploads = Upload.objects.all()
    checked_record_form = CheckedRecordForm()
    context = {
        'author_roles': author_roles,
        'classifications': classifications,
        'psced_classifications': psced_classifications,
        'conference_levels': conference_levels,
        'budget_types': budget_types,
        'collaboration_types': collaboration_types,
        'publication_levels': publication_levels,
        'uploads': uploads,
        'checked_record_form': checked_record_form,
        'is_owner': True,
    }

    @method_decorator(login_required(login_url='/'))
    @method_decorator(authorized_record_user())
    def get(self, request, record_id):
        owners = UserRecord.objects.filter(record=Record.objects.get(pk=record_id))
        for owner in owners:
            if owner.user.role.pk == 2:
                student = Student.objects.get(user=owner.user)
                owner.student = student
        self.context['owners'] = owners
        checked_records = CheckedRecord.objects.filter(record=Record.objects.get(pk=record_id))
        adviser_checked = {'status': 'pending'}
        ktto_checked = {'status': 'pending'}
        rdco_checked = {'status': 'pending'}
        role_checked = False
        record = Record.objects.get(pk=record_id)
        research_record = ResearchRecord.objects.filter(Q(proposal=record) | Q(research=record)).first()
        for checked_record in checked_records:
            if checked_record.checked_by.role.id == 3:
                adviser_checked = {'status': checked_record.status, 'content': checked_record}
            if checked_record.checked_by.role.id == 4 or checked_record.checked_by.role.id == 7:
                ktto_checked = {'status': checked_record.status, 'content': checked_record}
            if checked_record.checked_by.role.id == 5:
                rdco_checked = {'status': checked_record.status, 'content': checked_record}
            if checked_record.checked_by.role.id == request.user.role.pk:
                role_checked = True
        self.context['adviser_checked'] = adviser_checked
        self.context['ktto_checked'] = ktto_checked
        self.context['rdco_checked'] = rdco_checked
        self.context['role_checked'] = role_checked
        self.context['record'] = record
        self.context['is_removable'] = True
        self.context['research_record'] = research_record
        return render(request, self.name, self.context)

    def post(self, request, record_id):
        if is_ajax(request=request):
            # removing record
            if request.POST.get('remove', 'false') == 'true':
                del_record = Record.objects.get(pk=record_id)
                del_record.abstract_file.delete()
                del_record_uploads = RecordUpload.objects.filter(record=del_record)
                for del_record_upload in del_record_uploads:
                    del_record_upload.file.delete()
                del_record.delete()
                return JsonResponse({'success': True})
            # updating record tags
            elif request.POST.get('tags_update', 'false') == 'true':
                return JsonResponse(update_record_tags(request, record_id))
            # get uploaded document data
            elif request.POST.get('get_document', 'false') == 'true':
                upload = Upload.objects.get(pk=request.POST.get('upload_id', 0))
                record = Record.objects.get(pk=request.POST.get('record_id', 0))
                record_upload = RecordUpload.objects.filter(upload=upload, record=record).first()
                checked_uploads = CheckedUpload.objects.filter(record_upload=record_upload).order_by('-date_checked')
                comments = []
                checked_bys = []
                checked_dates = []
                for checked_upload in checked_uploads:
                    comments.append(checked_upload.comment)
                    checked_bys.append(checked_upload.checked_by.username)
                    checked_dates.append(checked_upload.date_checked)
                if record_upload is None:
                    return JsonResponse({'success': False, 'doc-title': upload.name})
                else:
                    return JsonResponse({'success': True,
                                         'doc-title': record_upload.upload.name,
                                         'doc-status': record_upload.record_upload_status.name,
                                         'is-ip': record_upload.is_ip,
                                         'for-commercialization': record_upload.for_commercialization,
                                         'comments': comments,
                                         'checked_bys': checked_bys,
                                         'checked_dates': checked_dates,
                                         'record-upload-id': record_upload.pk})
            # POSTING COMMENTS
            elif request.POST.get('post_comment', 'false') == 'true':
                upload = Upload.objects.get(pk=request.POST.get('upload_id', 0))
                record = Record.objects.get(pk=request.POST.get('record_id', 0))
                comment = request.POST.get('comment', '')
                record_upload = RecordUpload.objects.filter(upload=upload, record=record).first()
                CheckedUpload(comment=comment, checked_by=request.user, record_upload=record_upload).save()
                recordComment(request, request.user.id, record_id, UserRecord.objects.get(record=record_id).user.id)
                return JsonResponse({'success': True})
            else:
                return JsonResponse({'success': False})
        else:
            # approving or declining record
            if request.user.role.id > 2:
                checked_record_form = CheckedRecordForm(request.POST)
                if checked_record_form.is_valid():
                    checked_record = checked_record_form.save(commit=False)
                    checked_record.checked_by = request.user
                    checked_record.record = Record.objects.get(pk=record_id)
                    checked_record.status = request.POST.get('status')
                    checked_record.save()
                    status = request.POST.get('status')
                    recordStatus(request, request.user.id, record_id,
                                 UserRecord.objects.only('user').get(record=record_id).user.id, status)
                else:
                    print('invalid form')
                return redirect('records-view', record_id)


class DashboardManageAccounts(View):
    name = 'records/dashboard/accounts_view.html'

    @method_decorator(authorized_roles(roles=['ktto', 'rdco', 'tbi', 'itso']))
    @method_decorator(login_required(login_url='/'))
    def get(self, request):
        user_roles = UserRole.objects.all()
        context = {
            'user_roles': user_roles,
        }
        return render(request, self.name, context)

    def post(self, request):
        if is_ajax(request=request):
            # removing accounts
            if request.POST.get('remove-accounts'):
                accounts = request.POST.getlist('accounts[]')
                success = False
                for account_id in accounts:
                    del_account = User.objects.get(pk=int(account_id))
                    if not del_account.is_superuser:
                        del_account.delete()
                        success = True
                return JsonResponse({'success': success})
            # accounts role change
            elif request.POST.get('role-change') == 'true':
                accounts = request.POST.getlist('accounts[]')
                accounts_str = ''

                role_id = int(request.POST.get('role-radio'))
                for account_id in accounts:
                    user = User.objects.get(pk=int(account_id))
                    user.role = UserRole.objects.get(pk=role_id)
                    user.save()
                    if account_id == accounts[0]:
                        accounts_str += user.username
                    else:
                        accounts_str += f', {user.username}'
                    RoleRequest.objects.filter(user=user).delete()
                Log(user=request.user,
                    action=f'accounts: {accounts_str} account_role changed to \"{user.role}\" by: {request.user.username}').save()
                # roleRequestNotify(request.user.id, user.id)
                roleRequestApproved(request, request.user.id, user.id)


class LockoutPage(View):
    name = "records/lockout_page.html"

    def get(self, request):
        return render(request, self.name)


class LockedAccountsView(View):
    name = "records/dashboard/reset_locked_accounts.html"

    @method_decorator(authorized_roles(roles=['ktto', 'rdco', 'tbi', 'itso']))
    @method_decorator(login_required(login_url='/'))
    def get(self, request):
        attempts = AccessAttempt.objects.all()
        context = {
            'attempts': attempts,
        }
        return render(request, self.name, context)

    def post(self, request):
        if request.method == 'POST':
            if request.POST.get('resetAccount'):
                accounts = request.POST.getlist('listOfAccounts[]')
                print(accounts)
                for account in accounts:
                    reset(username=account)
                return JsonResponse({'success': True})


def get_all_download_requests(request):
    if request.method == 'POST':
        data = []
        download_requests = RecordDownloadRequest.objects.filter(is_marked=False)
        for record in download_requests:
            data.append([
                record.pk,
                '',
                record.record.title,
                record.sent_by.username,
                f'<div><a href="#" data-toggle="modal" data-target="#approvedDownloadModal" class="{record.sent_by.username}-{record.pk}" id="approve-btn-{record.record.pk}" onclick="return getModalId(this.id, this.className);"> Approve </a></div>'
            ])

        return JsonResponse({'data': data})


def approved_download_requests(request):
    if request.method == 'POST':
        if 'approvedDownloadBtn' in request.POST:
            record_id = request.POST.get('record_number')
            username = request.POST.get('username')
            request_id = request.POST.get('request_id')
            user = User.objects.get(username=username)
            download_request = RecordDownloadRequest.objects.get(pk=request_id)
            download_request.is_marked = True
            download_request.save()

            approvedDownloadRequest(request, request.user.id, record_id, user.id)
            return redirect("records-pending")
        else:
            messages.error(request, 'Error encountered while approving request')
            return redirect("records-pending")



class AuthenticationPinView(View):
    name = 'records/authenticaterecords.html'
    author_roles = AuthorRole.objects.all()
    classifications = Classification.objects.all()
    psced_classifications = PSCEDClassification.objects.all().order_by('name')
    conference_levels = ConferenceLevel.objects.all()
    budget_types = BudgetType.objects.all()
    collaboration_types = CollaborationType.objects.all()
    publication_levels = PublicationLevel.objects.all()
    uploads = Upload.objects.all()
    checked_record_form = CheckedRecordForm()
    context = {
        'author_roles': author_roles,
        'classifications': classifications,
        'psced_classifications': psced_classifications,
        'conference_levels': conference_levels,
        'budget_types': budget_types,
        'collaboration_types': collaboration_types,
        'publication_levels': publication_levels,
        'uploads': uploads,
        'checked_record_form': checked_record_form,
    }

    @method_decorator(login_required(login_url='/'))
    @method_decorator(authorized_record_user())
    def get(self, request, record_id):
        checked_records = CheckedRecord.objects.filter(record=Record.objects.get(pk=record_id))
        is_removable = False
        record = Record.objects.get(pk=record_id)
        record_uploads = record.recordupload_set.all()
        for checked_record in checked_records:
            if checked_record.status == 'declined':
                is_removable = True
        self.context['record'] = Record.objects.get(pk=record_id)
        self.context['is_removable'] = is_removable
        self.context['recorduploads'] = record_uploads
        return render(request, self.name, self.context)


    # class SendemailView(View):
    #     def ajax_post_pin(request):
    #        if request.method == 'POST':
    #            pin = request.POST.get('pin')
    #
    #             my_pin = myPin(pin=pin)
    #             my_pin.save()


# def send_email(request):
#     if request.method == 'POST':
#         pin = request.POST.get('pin')
#
#         # Send the email using Django's send_mail function
#         send_mail(
#             'Generated PIN',
#             f'Your generated PIN is: {pin}',
#             'glajera320@gmail.com',  # Replace with your email address
#             ['ipamsg2@gmail.com'],  # Replace with the recipient's email address
#             fail_silently=False,
#         )
#
#         return JsonResponse({'success': True})
#     else:
#         return JsonResponse({'error': 'Invalid request method.'})

@login_required
def generate_pin_and_save_data_view(request):
    if request.method == 'POST':
        pin = request.POST.get('pin')
        record_id = request.POST.get('record_id')  # Assuming you pass the record_id correctly in the POST data
        user_id = request.POST.get('user_id')

        try:
            # Fetch the 'record' object based on the provided 'record_id'
            record = Record.objects.get(pk=record_id)

            # Ensure that 'record' is not None and 'pin' is a valid PIN
            if record and pin:

                # Create a new RecordAuthenticationPin object with the provided 'pin' and 'record' as the foreign key
                record_auth_pin = RecordAuthenticationPin.objects.create(
                    record=record,
                    pin=pin,
                    user_id=user_id,  # Include user_id in the creation of the object
                    email=request.user.email
                )

                # Send the PIN to the user via email
                send_mail(
                    'Generated PIN',
                    f'Your generated PIN is: {pin}',
                    'glajera320@gmail.com',  # Replace with your email address
                    [request.user.email],  # Replace with the recipient's email address
                    fail_silently=False,
                )

                # Successfully created the RecordAuthenticationPin and sent the email
                return JsonResponse({'success': True})
            else:
                # Handle the case where 'record' is not found or 'pin' is empty or None
                return JsonResponse({'success': False, 'error_message': 'Invalid data'})
        except Exception as e:
            # Log the exception for debugging
            print(f"Error creating RecordAuthenticationPin: {e}")
            # Handle other exceptions here if needed


            # Send the PIN to the user via email even if there was an exception
            send_mail(
                'Generated PIN',
                f'Your generated PIN is: {pin}',
                'glajera320@gmail.com',  # Replace with your email address
                [request.user.email],  # Replace with the recipient's email address
                fail_silently=False,
            )

            return JsonResponse({'success': True})  # Return success even if there was an exception

    return JsonResponse({'success': False, 'error_message': 'Invalid request method'})

    return JsonResponse({'success': False, 'error_message': 'Invalid request method'})

#def upload_pin(request):
#    if request.method == 'POST':
#        if ''

def create_record(request):
    if request.method == 'POST':
        record_form = RecordForm(request.POST, request.FILES)
        file_form = RecordFileForm(request.POST, request.FILES)
        if record_form.is_valid():
            record = record_form.save()
            if file_form.is_valid():
                files = request.FILES.getlist('new_file')
                for file in files:
                    record_file = RecordFile(record=record, file=file)
                    record_file.save()
            return redirect('records-add')
    else:
        record_form = RecordForm()
        file_form = RecordFileForm()

    return render(request, 'title_and_abstract.html', {'record_form': record_form, 'file_form': file_form})

def records_accessed_view(request):
    # Calculate the count of records accessed today
    today = timezone.now().date()  # Get the current date
    records_accessed_count = Record.objects.filter(date_accessed__date=today).count()

    context = {
        'records_accessed_count': records_accessed_count,
        # Other context data
    }

    return render(request, 'home.html', context)

def browse_file_student(request):
    # Implement any necessary logic here

    # Redirect to the 'browse_file_student' view
    return render(request, 'browse_file_student.html')

def attachments_view(request, record_id):
    uploads = Upload.objects.all()
    records = Record.objects.filter(id=record_id)

    context = {
    'uploads': uploads,
    'records': records,
    }
    return render(request, 'attachments.html', context)

def attachment_files_view(request, record_id, upload_id):
    record = get_object_or_404(Record, id=record_id)
    upload = get_object_or_404(RecordUpload, upload_id=upload_id, record_id=record_id)

    if request.method == 'POST':
        # Handle file uploads
        uploaded_files = request.FILES.getlist('file')

        for uploaded_file in uploaded_files:
            record_upload = RecordUpload(
                file=uploaded_file,
                upload=upload,
                record=record,
                # ...other fields
            )
            record_upload.save()

            # Handle the uploaded file, for example, you can process it further

        return JsonResponse({'success': True})

    context = {
        'record': record,
        'upload': upload,
    }

    return render(request, 'attachment_files.html', context)
