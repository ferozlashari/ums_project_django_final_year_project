from django.core.management.base import BaseCommand
from risk_analytics.scoring import recalculate_risk_flags


class Command(BaseCommand):
    help = 'Recompute attendance/GPA-based early-warning risk flags for every active student. Safe to run repeatedly - schedule nightly with cron/Task Scheduler for a real early-warning system.'

    def handle(self, *args, **options):
        result = recalculate_risk_flags()
        self.stdout.write(self.style.SUCCESS(
            f"Scanned {result['scanned']} students - {result['newly_high_risk']} newly flagged high-risk."
        ))
