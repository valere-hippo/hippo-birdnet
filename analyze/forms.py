from django import forms
from .models import AudioFile

class AudioForm(forms.ModelForm):
    class Meta:
        model = AudioFile
        fields = ['audio']
