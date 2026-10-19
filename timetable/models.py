from django.db import models

class Room(models.Model):
    ROOM_TYPE_CHOICES = [
        ('lecture', 'Lecture Hall'), ('lab', 'Computer/Science Lab'),
        ('seminar', 'Seminar Room'), ('auditorium', 'Auditorium'),
    ]
    name = models.CharField(max_length=100)
    capacity = models.IntegerField(default=30)
    location = models.CharField(max_length=200, blank=True)
    building = models.CharField(max_length=150, blank=True)
    floor = models.CharField(max_length=50, blank=True)
    room_type = models.CharField(max_length=20, choices=ROOM_TYPE_CHOICES, default='lecture')
    has_projector = models.BooleanField(default=False)
    has_computers = models.BooleanField(default=False)
    def __str__(self): return self.name

class TimeSlot(models.Model):
    DAY_CHOICES = [('mon','Monday'),('tue','Tuesday'),('wed','Wednesday'),('thu','Thursday'),('fri','Friday'),('sat','Saturday')]
    day = models.CharField(max_length=10, choices=DAY_CHOICES)
    start_time = models.TimeField()
    end_time = models.TimeField()
    def __str__(self): return f"{self.get_day_display()} {self.start_time}-{self.end_time}"

class TimetableAssignment(models.Model):
    section = models.ForeignKey('academics.CourseSection', on_delete=models.CASCADE)
    room = models.ForeignKey(Room, on_delete=models.CASCADE)
    timeslot = models.ForeignKey(TimeSlot, on_delete=models.CASCADE)
    semester = models.ForeignKey('academics.Semester', on_delete=models.CASCADE, null=True, blank=True)
    STATUS_CHOICES = [('draft', 'Draft (awaiting approval)'), ('approved', 'Approved')]
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='approved')
    def __str__(self): return f"{self.section.code} @ {self.room.name} {self.timeslot}"