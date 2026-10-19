from django import forms
from .models import TimetableAssignment, Room

class TimetableForm(forms.ModelForm):
    class Meta:
        model = TimetableAssignment
        fields = '__all__'


class RoomForm(forms.ModelForm):
    class Meta:
        model = Room
        fields = '__all__'
