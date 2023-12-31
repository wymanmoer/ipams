from django.contrib import admin
from django.urls import path, include, re_path
# import debug_toolbar
from django.views.static import serve
from ipams import settings
from django.conf.urls.static import static
urlpatterns = [
    re_path(r'^media/(?P<path>.*)$', serve,{'document_root': settings.MEDIA_ROOT}), 
    re_path(r'^static/(?P<path>.*)$', serve,{'document_root': settings.STATIC_ROOT}),
    path('', include('records.urls')),
    path('account/', include('accounts.urls')),
    path('notifications/', include('notifications.urls')),
    path('admin/', admin.site.urls),
    path('file_management/', include('file_management.urls')),
    # path('__debug__/', include(debug_toolbar.urls)),
]   + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
