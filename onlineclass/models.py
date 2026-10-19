import secrets
from django.db import models
from django.utils import timezone


class OnlineClass(models.Model):
    """A scheduled live video class. Uses a free Jitsi Meet room (no
    external account or API key needed) - the room name is a random,
    hard-to-guess slug so only people with the link/room code can join."""
    STATUS_CHOICES = [('scheduled', 'Scheduled'), ('live', 'Live Now'), ('ended', 'Ended')]

    title = models.CharField(max_length=200)
    section = models.ForeignKey('academics.CourseSection', on_delete=models.CASCADE, related_name='online_classes')
    semester = models.ForeignKey('academics.Semester', on_delete=models.CASCADE, related_name='online_classes', null=True, blank=True)
    host = models.ForeignKey('hr.Staff', on_delete=models.CASCADE, related_name='hosted_classes')
    room_code = models.CharField(max_length=40, unique=True, blank=True)
    scheduled_at = models.DateTimeField()
    duration_mins = models.PositiveIntegerField(default=60)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='scheduled')
    notes = models.TextField(blank=True, help_text='Agenda or notes shared with students')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-scheduled_at']
        verbose_name = 'Online Class'
        verbose_name_plural = 'Online Classes'

    def save(self, *args, **kwargs):
        if not self.room_code:
            self.room_code = f'ums-{secrets.token_urlsafe(12)}'
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.title} ({self.section.course.code})'

    @property
    def is_joinable(self):
        """Joinable from 10 minutes before the scheduled time until it's marked ended."""
        if self.status == 'ended':
            return False
        now = timezone.now()
        window_start = self.scheduled_at - timezone.timedelta(minutes=10)
        window_end = self.scheduled_at + timezone.timedelta(minutes=self.duration_mins + 30)
        return window_start <= now <= window_end

    @property
    def display_status(self):
        """What should actually be shown right now - 'scheduled', 'live',
        or 'ended'. The stored `status` field only ever changes when a
        teacher explicitly clicks End (see class_end view); left alone,
        a class sits at its default 'scheduled' forever even once it's
        actually live or long finished. An explicit 'ended' always wins;
        otherwise this is computed from real elapsed time against
        scheduled_at/duration_mins, so the badge reflects reality even
        if nobody ever clicks End."""
        if self.status == 'ended':
            return 'ended'
        now = timezone.now()
        if now < self.scheduled_at:
            return 'scheduled'
        if now <= self.scheduled_at + timezone.timedelta(minutes=self.duration_mins):
            return 'live'
        return 'ended'

    @property
    def display_status_label(self):
        return dict(self.STATUS_CHOICES).get(self.display_status, self.display_status)

    @property
    def jitsi_room_url(self):
        return f'https://meet.jit.si/{self.room_code}'
