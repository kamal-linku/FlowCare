from app.services.simulation import compare_scenarios, simulate_day


def test_simulation_is_repeatable_and_compares_shared_arrivals():
    first = compare_scenarios(
        patients=80, arrival_rate_per_hour=12, service_mean=15,
        baseline_doctors=2, alternative_doctors=3, seed=1234,
    )
    second = compare_scenarios(
        patients=80, arrival_rate_per_hour=12, service_mean=15,
        baseline_doctors=2, alternative_doctors=3, seed=1234,
    )
    assert first == second
    assert first["arrivals_shared"] is True
    assert first["alternative"]["average_wait_minutes"] <= first["baseline"]["average_wait_minutes"]


def test_simulation_handles_zero_staff():
    result = simulate_day(arrivals=[(1.0, False), (4.0, True)], doctors=0, service_mean=10, seed=1)
    assert result["average_wait_minutes"] is None
    assert result["patients"] == 2
