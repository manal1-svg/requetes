from django.conf import settings
from django.contrib import admin
from django.urls import path, include
from django.conf.urls.static import static
from lettres import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('lettres.urls')),
      path('', views.dashboard, name='dashboard'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('new_lettres/', views.new_lettres, name='new_lettres'),
    path('destinations/', views.destinations, name='destinations'),
    path('statistics/', views.statistics, name='statistics'),
    path('archive/', views.archive, name='archive'),
    path('settings/', views.settings_page, name='settings'),
    path('destination/<str:destination_name>/', views.destination_interface, name='destination_interface'),
    path('lettre/<int:pk>/send_email_reminder/', views.send_email_reminder, name='send_email_reminder'),
    path('send_automatic_reminders/', views.send_automatic_reminders, name='send_automatic_reminders'),
    path('lettre/<int:pk>/send_global_reminder/', views.send_global_reminder, name='send_global_reminder'),
    path('dashboard_reponse/', views.dashboard_Reponse, name='dashboard_Reponse'),
    path('lettre/<int:lettre_id>/submit_response/', views.submit_response, name='submit_response'),
    path('lettre/<int:pk>/detail/', views.lettre_detail, name='lettre_detail'),
    path('lettre/<int:pk>/rappels/<str:destination_name>/', views.get_rappels, name='get_rappels'),

 
   
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)