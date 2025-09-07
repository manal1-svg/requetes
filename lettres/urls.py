# lettres/urls.py
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from .views import approve_response
from . import views

app_name = 'lettres'

urlpatterns = [
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
    path('lettre/<int:lettre_id>/submit_response/', views.submit_response, name='submit_response'),
    path('lettre/<int:pk>/detail/', views.lettre_detail, name='lettre_detail'),
    path('lettre/<int:pk>/rappels/<str:destination_name>/', views.get_rappels, name='get_rappels'),
    path('dashboard/response/', views.dashboard_Reponse, name='dashboard_Reponse'),
    path('<int:lettre_id>/submit_response/', views.submit_response, name='submit_response'),
    path('response/<int:response_id>/', views.response_detail, name='response_detail'),
    path('profile/', views.profile, name='profile'),
    path('response/<int:response_id>/detail/', views.response_detail, name='response_detail'),
   
    path('submit_response/<int:lettre_id>/', views.submit_response, name='submit_response'),
    path('dashboard_Reponse/', views.dashboard_Reponse, name='dashboard_Reponse'),
    path('approve_response/<int:response_id>/', approve_response, name='approve_response'),
    
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
