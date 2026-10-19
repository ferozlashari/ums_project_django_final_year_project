from django import forms
from .models import Vehicle, Route, RouteStop, StudentTransportAssignment


class VehicleForm(forms.ModelForm):
    class Meta:
        model = Vehicle
        fields = ['registration_no', 'capacity', 'driver_name', 'driver_phone', 'is_active']


class RouteForm(forms.ModelForm):
    class Meta:
        model = Route
        fields = ['name', 'fare_per_semester', 'vehicle', 'is_active']


class RouteStopForm(forms.ModelForm):
    class Meta:
        model = RouteStop
        fields = ['route', 'name', 'pickup_time', 'order']
        widgets = {'pickup_time': forms.TimeInput(attrs={'type': 'time'})}


class AssignTransportForm(forms.ModelForm):
    admission_no = forms.CharField(max_length=120, label='Student admission number')

    class Meta:
        model = StudentTransportAssignment
        fields = ['route', 'stop']

    def clean_admission_no(self):
        from registration.models import Student
        admission_no = self.cleaned_data['admission_no'].strip()
        if not Student.objects.filter(admission_no=admission_no).exists():
            raise forms.ValidationError('No student found with that admission number.')
        return admission_no
