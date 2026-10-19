"""Timetable conflict detection and draft generation.

Generated entries are DRAFTS. Nothing becomes part of the official timetable
until an administrator approves it."""
from collections import defaultdict

from academics.models import CourseRegistration, CourseSection
from .models import Room, TimeSlot, TimetableAssignment


def slots_overlap(a, b):
    return a.day == b.day and a.start_time < b.end_time and b.start_time < a.end_time


class TimetableService:
    @staticmethod
    def conflicts(semester):
        """Teacher, room, same-section and student clashes for one semester."""
        rows = list(TimetableAssignment.objects.filter(semester=semester)
                    .select_related('section__course', 'section__instructor__user', 'room', 'timeslot'))
        found = []

        def pairs(items):
            for i in range(len(items)):
                for j in range(i + 1, len(items)):
                    yield items[i], items[j]

        by_teacher, by_room, by_section = defaultdict(list), defaultdict(list), defaultdict(list)
        for r in rows:
            if r.section.instructor_id:
                by_teacher[r.section.instructor_id].append(r)
            by_room[r.room_id].append(r)
            by_section[r.section_id].append(r)
        for kind, groups, label in (('teacher', by_teacher, 'Teacher'), ('room', by_room, 'Room'), ('section', by_section, 'Section')):
            for items in groups.values():
                for a, b in pairs(items):
                    if slots_overlap(a.timeslot, b.timeslot):
                        found.append({'kind': kind, 'message': f'{label} clash: {a.section} and {b.section} overlap on {a.timeslot}.'})
        slots_by_section = {sid: [r.timeslot for r in items] for sid, items in by_section.items()}
        student_sections = defaultdict(set)
        for student_id, section_id in CourseRegistration.objects.filter(semester=semester, status='registered').values_list('student_id', 'section_id'):
            if section_id in slots_by_section:
                student_sections[student_id].add(section_id)
        seen = set()
        for student_id, sections in student_sections.items():
            for x, y in pairs(sorted(sections)):
                if (x, y) in seen:
                    continue
                if any(slots_overlap(p, q) for p in slots_by_section[x] for q in slots_by_section[y]):
                    seen.add((x, y))
                    found.append({'kind': 'student', 'message': f'Student clash: sections {x} and {y} overlap for at least one registered student.'})
        return found

    @classmethod
    def generate(cls, semester, dry_run=False):
        """Greedy draft timetable for registered sections that have no slot yet.
        Respects: teacher free, room free, room big enough, lab sections in
        lab rooms, and no clash for students who share sections."""
        existing = list(TimetableAssignment.objects.filter(semester=semester).select_related('timeslot', 'section', 'room'))
        placed_sections = {e.section_id for e in existing}
        slots_by_section = defaultdict(list)
        teacher_slots, room_slots = defaultdict(list), defaultdict(list)
        for e in existing:
            slots_by_section[e.section_id].append(e.timeslot)
            if e.section.instructor_id:
                teacher_slots[e.section.instructor_id].append(e.timeslot)
            room_slots[e.room_id].append(e.timeslot)

        regs = defaultdict(set)              # section -> students
        student_sections = defaultdict(set)  # student -> sections
        for student_id, section_id in CourseRegistration.objects.filter(semester=semester, status='registered').values_list('student_id', 'section_id'):
            regs[section_id].add(student_id)
            student_sections[student_id].add(section_id)

        sections = [s for s in CourseSection.objects.filter(pk__in=regs.keys()).select_related('course', 'instructor')
                    if s.pk not in placed_sections]
        sections.sort(key=lambda s: (-len(regs[s.pk]), s.pk))
        rooms = list(Room.objects.order_by('capacity', 'name'))
        timeslots = list(TimeSlot.objects.order_by('day', 'start_time'))
        result = {'placed': [], 'unplaced': []}
        if not rooms or not timeslots:
            result['unplaced'] = [{'section': s, 'reason': 'No rooms or time slots are configured.'} for s in sections]
            return result

        for section in sections:
            need = len(regs[section.pk])
            wants_lab = section.section_type == 'lab'
            candidate_rooms = [r for r in rooms if r.capacity >= max(need, 1) and (r.room_type == 'lab') == wants_lab]
            neighbours = {sid for st in regs[section.pk] for sid in student_sections[st]} - {section.pk}
            reason = 'No suitable room is large enough.' if not candidate_rooms else 'No free time slot without a clash.'
            done = False
            for ts in timeslots:
                if section.instructor_id and any(slots_overlap(ts, o) for o in teacher_slots[section.instructor_id]):
                    continue
                if any(slots_overlap(ts, o) for sid in neighbours for o in slots_by_section[sid]):
                    continue
                room = next((r for r in candidate_rooms if not any(slots_overlap(ts, o) for o in room_slots[r.pk])), None)
                if room is None:
                    continue
                if not dry_run:
                    TimetableAssignment.objects.create(section=section, room=room, timeslot=ts, semester=semester, status='draft')
                slots_by_section[section.pk].append(ts)
                room_slots[room.pk].append(ts)
                if section.instructor_id:
                    teacher_slots[section.instructor_id].append(ts)
                result['placed'].append({'section': section, 'room': room, 'timeslot': ts})
                done = True
                break
            if not done:
                result['unplaced'].append({'section': section, 'reason': reason})
        return result

    @staticmethod
    def approve_drafts(semester):
        """Admin approval: only allowed while the drafts are conflict-free."""
        problems = TimetableService.conflicts(semester)
        if problems:
            raise ValueError(f'{len(problems)} conflict(s) must be resolved before approval.')
        return TimetableAssignment.objects.filter(semester=semester, status='draft').update(status='approved')
