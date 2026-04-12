from django import forms
from .models import User, Api

class UserRegisterForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput())
    class Meta:
        model = User
        fields = ['name', 'email']

class ApiForm(forms.ModelForm):
    api_key_encrypted = forms.CharField(widget=forms.PasswordInput())
    class Meta:
        model = Api
        fields = ['model_name', 'api_key_encrypted', 'is_mandatory']