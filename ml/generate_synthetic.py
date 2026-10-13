import argparse
import csv
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


def generate(output: Path, days: int = 90, seed: int = 2025) -> None:
    rng = random.Random(seed)
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "arrival_at", "department", "patients_ahead", "available_staff",
        "occupied_staff", "typical_service_minutes", "hour", "is_appointment",
        "actual_wait_minutes",
    ]
    start = datetime.combine(date.today() - timedelta(days=days), datetime.min.time(), tzinfo=timezone.utc)
    departments = [("General Medicine", 15), ("Cardiology", 20), ("Orthopedics", 18)]
    with output.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for day in range(days):
            for department, service in departments:
                count = rng.randint(35, 80)
                for _ in range(count):
                    hour = rng.choices(range(8, 18), weights=[1, 2, 3, 4, 5, 5, 4, 4, 3, 2])[0]
                    ahead = rng.randint(0, 18)
                    staff = rng.randint(1, 4)
                    occupied = rng.randint(0, staff)
                    appointment = rng.random() < 0.65
                    # Synthetic event outcome with explicit queue features and noise.
                    wait = max(
                        0.0,
                        (ahead * service / max(1, staff) + occupied * service / max(1, staff))
                        * (1.12 if hour in (11, 12, 13) else 0.88)
                        + rng.gauss(0, 7),
                    )
                    arrived = start + timedelta(days=day, hours=hour, minutes=rng.randrange(60))
                    writer.writerow({
                        "arrival_at": arrived.isoformat(),
                        "department": department,
                        "patients_ahead": ahead,
                        "available_staff": staff,
                        "occupied_staff": occupied,
                        "typical_service_minutes": service,
                        "hour": hour,
                        "is_appointment": int(appointment),
                        "actual_wait_minutes": round(wait, 2),
                    })
    print(f"Wrote synthetic event rows to {output} (seed={seed}, days={days}).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate reproducible synthetic FlowCare queue events.")
    parser.add_argument("--output", type=Path, default=Path("ml/data/generated/synthetic_events.csv"))
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--seed", type=int, default=2025)
    args = parser.parse_args()
    generate(args.output, args.days, args.seed)
