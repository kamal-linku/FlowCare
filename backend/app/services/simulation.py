import heapq
import random
from statistics import mean


def simulate_day(
    *,
    arrivals: list[tuple[float, bool]],
    doctors: int,
    service_mean: float,
    seed: int,
) -> dict:
    if doctors < 0:
        raise ValueError("Doctor count cannot be negative.")
    rng = random.Random(seed)
    if not arrivals:
        return {
            "patients": 0,
            "average_wait_minutes": 0.0,
            "p90_wait_minutes": 0.0,
            "maximum_queue": 0,
            "throughput_per_hour": 0.0,
            "staff_utilization_percent": 0.0,
            "waits": [],
        }
    if doctors == 0:
        waits = [0.0] * len(arrivals)
        return {
            "patients": len(arrivals),
            "average_wait_minutes": None,
            "p90_wait_minutes": None,
            "maximum_queue": len(arrivals),
            "throughput_per_hour": 0.0,
            "staff_utilization_percent": 0.0,
            "waits": waits,
        }

    available = [0.0] * doctors
    heapq.heapify(available)
    waits: list[float] = []
    occupied_work = 0.0
    maximum_queue = 0
    scheduled_starts: list[float] = []
    for arrival, is_appointment in arrivals:
        free_at = heapq.heappop(available)
        start = max(arrival, free_at)
        waiting_now = sum(start_time > arrival for start_time in scheduled_starts)
        maximum_queue = max(maximum_queue, waiting_now + int(start > arrival))
        scheduled_starts.append(start)
        waits.append(start - arrival)
        duration = max(3.0, rng.gauss(service_mean * (0.9 if is_appointment else 1.05), service_mean * 0.22))
        finish = start + duration
        occupied_work += duration
        heapq.heappush(available, finish)

    total_hours = max(1 / 60, max(available) / 60)
    sorted_waits = sorted(waits)
    p90 = sorted_waits[min(len(sorted_waits) - 1, int(0.9 * (len(sorted_waits) - 1)))]
    return {
        "patients": len(arrivals),
        "average_wait_minutes": round(mean(waits), 1),
        "p90_wait_minutes": round(p90, 1),
        "maximum_queue": maximum_queue,
        "throughput_per_hour": round(len(arrivals) / total_hours, 1),
        "staff_utilization_percent": round(
            min(100.0, 100 * occupied_work / (doctors * total_hours * 60)), 1
        ),
        "waits": [round(wait, 1) for wait in waits],
    }


def compare_scenarios(
    *, patients: int, arrival_rate_per_hour: float, service_mean: float,
    baseline_doctors: int, alternative_doctors: int, seed: int
) -> dict:
    if patients < 1 or patients > 5000:
        raise ValueError("Patient count must be between 1 and 5000.")
    if arrival_rate_per_hour <= 0 or service_mean <= 0:
        raise ValueError("Arrival rate and service duration must be positive.")
    rng = random.Random(seed)
    arrivals: list[tuple[float, bool]] = []
    arrival = 0.0
    for index in range(patients):
        arrival += rng.expovariate(arrival_rate_per_hour / 60)
        arrivals.append((arrival, rng.random() < 0.65))
    baseline = simulate_day(
        arrivals=arrivals, doctors=baseline_doctors, service_mean=service_mean, seed=seed + 1
    )
    alternative = simulate_day(
        arrivals=arrivals, doctors=alternative_doctors, service_mean=service_mean, seed=seed + 1
    )
    return {
        "label": "SIMULATED - not observed hospital performance",
        "seed": seed,
        "arrivals_shared": True,
        "baseline": {key: value for key, value in baseline.items() if key != "waits"},
        "alternative": {key: value for key, value in alternative.items() if key != "waits"},
        "difference": {
            "average_wait_minutes": (
                round(alternative["average_wait_minutes"] - baseline["average_wait_minutes"], 1)
                if alternative["average_wait_minutes"] is not None
                and baseline["average_wait_minutes"] is not None
                else None
            ),
            "p90_wait_minutes": (
                round(alternative["p90_wait_minutes"] - baseline["p90_wait_minutes"], 1)
                if alternative["p90_wait_minutes"] is not None
                and baseline["p90_wait_minutes"] is not None
                else None
            ),
        },
    }
