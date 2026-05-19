"""Scheduled jobs for auto-marking absenteeism."""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from models.schedule import Schedule, ScheduleStatus
from models.checkin import Checkin, CheckinStatus
from models.absenteeism import Absenteeism
from models.reminder import Reminder


def auto_mark_absent(db: Session):
    """
    Check schedules that ended more than 1 hour ago without a completed checkin.
    Marks them as absenteeism and creates reminders.
    """
    one_hour_ago = datetime.utcnow() - timedelta(hours=1)

    overdue_schedules = db.query(Schedule).filter(
        Schedule.end_time <= one_hour_ago,
        Schedule.status == ScheduleStatus.ASSIGNED,
    ).all()

    for schedule in overdue_schedules:
        # Check if there's already an absenteeism record
        existing_absent = db.query(Absenteeism).filter(
            Absenteeism.schedule_id == schedule.id,
        ).first()
        if existing_absent:
            continue

        # Check if there's a completed checkin for this schedule
        completed_checkin = db.query(Checkin).filter(
            Checkin.schedule_id == schedule.id,
            Checkin.status == CheckinStatus.COMPLETED,
        ).first()

        if not completed_checkin:
            # Mark schedule as completed
            schedule.status = ScheduleStatus.COMPLETED

            # Create absenteeism record
            absent = Absenteeism(
                schedule_id=schedule.id,
                worker_id=schedule.worker_id,
                patient_id=schedule.patient_id,
                status="absent",
                auto_marked_at=datetime.utcnow(),
            )
            db.add(absent)

            # Create reminder
            reminder = Reminder(
                worker_id=schedule.worker_id,
                schedule_id=schedule.id,
                type="未提交提醒",
                message=(
                    f"您于 {schedule.start_time.strftime('%Y-%m-%d %H:%M')} "
                    f"至 {schedule.end_time.strftime('%H:%M')} 的服务未提交护理记录"
                ),
            )
            db.add(reminder)

    db.commit()
