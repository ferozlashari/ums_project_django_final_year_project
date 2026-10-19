def has_conflict(qs, room, timeslot):
    # naive check: does an assignment exist for same room+timeslot
    return qs.filter(room=room, timeslot=timeslot).exists()