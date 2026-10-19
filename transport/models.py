from django.db import models


class Vehicle(models.Model):
    """A physical bus/van on the fleet."""
    registration_no = models.CharField(max_length=30, unique=True)
    capacity = models.PositiveIntegerField(default=40)
    driver_name = models.CharField(max_length=150, blank=True)
    driver_phone = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['registration_no']

    def __str__(self):
        return self.registration_no


class Route(models.Model):
    """One bus route, e.g. 'Route 4 - Gulshan/North Nazimabad'."""
    name = models.CharField(max_length=150)
    fare_per_semester = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    vehicle = models.ForeignKey(Vehicle, on_delete=models.SET_NULL, null=True, blank=True, related_name='routes')
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def seats_taken(self):
        return self.assignments.filter(is_active=True).count()

    @property
    def seats_available(self):
        if not self.vehicle:
            return None
        return max(0, self.vehicle.capacity - self.seats_taken)


class RouteStop(models.Model):
    """A pickup/drop-off point along a route, in order."""
    route = models.ForeignKey(Route, on_delete=models.CASCADE, related_name='stops')
    name = models.CharField(max_length=150, help_text='e.g. "Main Gate", "Askari Chowk"')
    pickup_time = models.TimeField()
    order = models.PositiveIntegerField(default=0, help_text='Stop order along the route (1 = first).')

    class Meta:
        ordering = ['route', 'order']

    def __str__(self):
        return f'{self.route.name} - {self.name} ({self.pickup_time.strftime("%H:%M")})'


class StudentTransportAssignment(models.Model):
    """A student's active subscription to one route + pickup stop."""
    student = models.OneToOneField('registration.Student', on_delete=models.CASCADE, related_name='transport_assignment')
    route = models.ForeignKey(Route, on_delete=models.CASCADE, related_name='assignments')
    stop = models.ForeignKey(RouteStop, on_delete=models.SET_NULL, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    assigned_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.student.full_name} -> {self.route.name}'
