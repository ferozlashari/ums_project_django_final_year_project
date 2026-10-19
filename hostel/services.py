"""Hostel room recommendation. A recommendation is only a suggestion: an
officer still approves the allocation (review screen)."""
from .models import Hostel, HostelApplication, Room


class HostelRecommendationService:
    @staticmethod
    def recommend_room(application):
        """Best available room for this application, or (None, reason).

        Rules: only the student's gender-matched active hostels; the applied
        hostel first if one was chosen; the preferred room type first, any type
        as a fallback; never a full room; prefer partly-filled rooms so rooms
        fill up before new ones open."""
        student = application.student
        if not student.gender:
            return None, 'Student gender is not set.'
        hostels = Hostel.objects.filter(is_active=True, gender=student.gender)
        if application.hostel_id:
            hostels = hostels.filter(pk=application.hostel_id)
        rooms = [r for r in Room.objects.filter(hostel__in=hostels).select_related('hostel') if not r.is_full]
        if not rooms:
            return None, 'No room with a free bed in a matching hostel.'
        preferred = [r for r in rooms if r.room_type == application.room_type_preference] or rooms
        preferred.sort(key=lambda r: (-r.occupied_count, r.hostel_id or 0, r.block, r.number))
        return preferred[0], 'Recommended'

    @classmethod
    def recommend_pending(cls):
        """Fill `recommended_room` for every pending application, counting the
        beds already suggested in this pass so one bed is not suggested twice."""
        results = []
        taken = {}
        for app in HostelApplication.objects.filter(status='pending').select_related('student', 'hostel').order_by('applied_at', 'pk'):
            room, reason = cls.recommend_room(app)
            if room is not None and taken.get(room.pk, 0) + room.occupied_count >= room.capacity:
                room, reason = None, 'Suggested beds are already used by earlier applicants.'
            if room is not None:
                taken[room.pk] = taken.get(room.pk, 0) + 1
            app.recommended_room = room
            app.save(update_fields=['recommended_room'])
            results.append((app, room, reason))
        return results
