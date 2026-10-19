from django import forms
from .models import HostelApplication, Room, Hostel


class HostelApplicationForm(forms.ModelForm):
    class Meta:
        model = HostelApplication
        fields = ['hostel', 'room_type_preference', 'cnic_copy', 'guardian_consent_letter', 'medical_certificate']

    def __init__(self, *args, student_gender=None, **kwargs):
        super().__init__(*args, **kwargs)
        # CNIC copy is the one document every applicant must provide -
        # required here at the form level (not the model) so existing rows
        # from before this field existed are never broken by a migration.
        self.fields['cnic_copy'].required = True
        # Only show hostels matching the applicant's own gender - never let
        # someone pick a hostel meant for the opposite gender.
        qs = Hostel.objects.filter(is_active=True)
        if student_gender:
            qs = qs.filter(gender=student_gender)
        else:
            qs = qs.none()
        self.fields['hostel'].queryset = qs
        self.fields['hostel'].required = True
        self.fields['hostel'].help_text = (
            'Only hostels matching your registered gender are shown.' if student_gender
            else 'Set your gender in your profile first - hostel options are gender-matched for safety and cannot be shown until then.'
        )


class RoomForm(forms.ModelForm):
    class Meta:
        model = Room
        fields = ['hostel', 'block', 'number', 'room_type', 'capacity']


class HostelForm(forms.ModelForm):
    class Meta:
        model = Hostel
        fields = ['name', 'gender', 'warden_name', 'warden_phone', 'address', 'is_active']


class AssignRoomForm(forms.ModelForm):
    class Meta:
        model = HostelApplication
        fields = ['assigned_room', 'status', 'remarks']

    def __init__(self, *args, **kwargs):
        instance = kwargs.get('instance')
        super().__init__(*args, **kwargs)
        if instance and instance.hostel_id:
            # Only let admin assign a room that actually belongs to the
            # hostel this application is for.
            self.fields['assigned_room'].queryset = Room.objects.filter(hostel=instance.hostel)
