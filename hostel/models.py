from django.db import models

from core.upload_validators import validate_document_upload


class Hostel(models.Model):
    """A physical hostel building/block - separate from Room so an
    institution can run distinct male/female hostels (a common real-world
    requirement) rather than mixing genders within one building."""
    GENDER_CHOICES = [('male', "Boys' Hostel"), ('female', "Girls' Hostel")]

    name = models.CharField(max_length=150, help_text='e.g. "Iqbal Hall", "Fatima Jinnah Hostel"')
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES)
    warden_name = models.CharField(max_length=150, blank=True)
    warden_phone = models.CharField(max_length=20, blank=True)
    address = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.get_gender_display()})'

    @property
    def total_capacity(self):
        return sum(r.capacity for r in self.rooms.all())

    @property
    def total_occupied(self):
        return sum(r.occupied_count for r in self.rooms.all())


class Room(models.Model):
    ROOM_TYPE_CHOICES = [('single', 'Single'), ('shared', 'Shared (2)'), ('dorm', 'Dormitory (4+)')]
    hostel = models.ForeignKey(Hostel, on_delete=models.CASCADE, related_name='rooms', null=True, blank=True)
    block = models.CharField(max_length=50)
    number = models.CharField(max_length=20)
    room_type = models.CharField(max_length=20, choices=ROOM_TYPE_CHOICES, default='shared')
    capacity = models.PositiveIntegerField(default=2)

    class Meta:
        unique_together = ('block', 'number')

    def __str__(self):
        return f'{self.hostel.name + " - " if self.hostel else ""}{self.block}-{self.number}'

    @property
    def occupied_count(self):
        return self.applications.filter(status='approved').count()

    @property
    def is_full(self):
        return self.occupied_count >= self.capacity


class HostelApplication(models.Model):
    STATUS_CHOICES = [('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')]
    student = models.ForeignKey('registration.Student', on_delete=models.CASCADE, related_name='hostel_applications')
    hostel = models.ForeignKey(Hostel, on_delete=models.SET_NULL, null=True, blank=True, related_name='applications')
    room_type_preference = models.CharField(max_length=20, choices=Room.ROOM_TYPE_CHOICES, default='shared')
    assigned_room = models.ForeignKey(Room, on_delete=models.SET_NULL, null=True, blank=True, related_name='applications')
    recommended_room = models.ForeignKey(Room, on_delete=models.SET_NULL, null=True, blank=True, related_name='recommended_for', help_text='System suggestion only - an officer still approves the allocation.')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    applied_at = models.DateTimeField(auto_now_add=True)
    remarks = models.CharField(max_length=255, blank=True)

    # Required supporting documents - a real hostel application always
    # needs these; kept as uploaded files rather than free text so admin
    # can actually verify them.
    cnic_copy = models.FileField(upload_to='hostel_docs/cnic/%Y/%m/', blank=True, default='', validators=[validate_document_upload], help_text='Scanned copy of CNIC/B-Form (PDF/JPG/PNG, max 5MB).')
    guardian_consent_letter = models.FileField(upload_to='hostel_docs/consent/%Y/%m/', null=True, blank=True, validators=[validate_document_upload], help_text='Signed guardian consent letter (required for undergraduate applicants).')
    medical_certificate = models.FileField(upload_to='hostel_docs/medical/%Y/%m/', null=True, blank=True, validators=[validate_document_upload], help_text='Recent medical fitness certificate, if your campus requires one.')

    def __str__(self):
        return f'{self.student.full_name} ({self.get_status_display()})'
