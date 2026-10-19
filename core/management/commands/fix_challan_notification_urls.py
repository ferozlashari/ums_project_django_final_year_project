from django.core.management.base import BaseCommand


class Command(BaseCommand):
    """One-off data fix: notifications created before the finance-challan
    URL bug was fixed still have the broken plural '/finance/challans/<id>/'
    saved in their `url` field (fixing the view code doesn't retroactively
    change rows already written to the database). This rewrites those rows
    to the correct singular '/finance/challan/<id>/' path.

    Safe to run more than once - it only touches rows that still contain
    the old broken pattern, so a second run just finds nothing to fix.
    """
    help = "Fix old notifications that still point at the broken /finance/challans/<id>/ URL"

    def handle(self, *args, **options):
        from core.models import Notification

        broken = Notification.objects.filter(url__contains='/finance/challans/')
        count = broken.count()

        if count == 0:
            self.stdout.write(self.style.SUCCESS('No broken notification URLs found. Nothing to do.'))
            return

        fixed = 0
        for note in broken:
            new_url = note.url.replace('/finance/challans/', '/finance/challan/')
            if new_url != note.url:
                note.url = new_url
                note.save(update_fields=['url'])
                fixed += 1

        self.stdout.write(self.style.SUCCESS(f'Fixed {fixed} of {count} broken notification URL(s).'))
