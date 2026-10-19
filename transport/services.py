"""Transport recommendation: match a student's address to route stops and
check seats. Never assigns "any" route - if nothing matches it says so."""
import re

from .models import Route, RouteStop, StudentTransportAssignment


def _words(text):
    return {w for w in re.findall(r'[a-z0-9]+', (text or '').lower()) if len(w) > 2}


class TransportRecommendationService:
    @staticmethod
    def recommend(student):
        """Returns (route, stop, reason). Stops whose name words appear in the
        student's address score highest; the route must be active and have a
        free seat. Returns (None, None, reason) when there is no real match."""
        if StudentTransportAssignment.objects.filter(student=student, is_active=True).exists():
            return None, None, 'Already has a transport assignment.'
        address = _words(getattr(student, 'address', '')) | _words(getattr(student, 'district', ''))
        if not address:
            return None, None, 'Student has no address on file.'
        best = None
        for stop in RouteStop.objects.filter(route__is_active=True).select_related('route__vehicle'):
            route = stop.route
            seats = route.seats_available
            if seats is not None and seats <= 0:
                continue
            score = len(_words(stop.name) & address)
            if score == 0:
                continue
            key = (score, seats if seats is not None else 0)
            if best is None or key > best[0]:
                best = (key, route, stop)
        if best is None:
            return None, None, 'No route stop matches the student address (or matching routes are full).'
        return best[1], best[2], 'Recommended'

    @classmethod
    def recommendations(cls):
        from registration.models import Student
        rows = []
        for student in Student.objects.filter(status='active').exclude(transport_assignment__is_active=True).order_by('full_name'):
            route, stop, reason = cls.recommend(student)
            rows.append({'student': student, 'route': route, 'stop': stop, 'reason': reason})
        return rows
