from django.urls import path
from . import views

urlpatterns = [
    path('', views.upload_audio, name='upload'),
    path('export_excel/', views.export_excel, name='export_excel'),
]
