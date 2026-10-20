"""Display charging energy without changing battery-side consumption estimates."""
from .usage_events import number, total


def preferred(row):
    bill=row.get('bill') or {}
    metered=number(bill.get('metered_kwh'),0,10000)
    if metered is not None:return metered,'metered'
    estimated=number(row.get('estimated_kwh'),0,10000)
    return (estimated,'soc_estimate') if estimated is not None else (None,None)


def summary(rows):
    values=[preferred(row) for row in rows]
    return dict(charging_kwh=total(value for value,_ in values),
                charging_energy_samples=sum(value is not None for value,_ in values),
                metered_energy_samples=sum(source=='metered' for _,source in values),
                soc_energy_samples=sum(source=='soc_estimate' for _,source in values),
                unknown_energy_samples=sum(value is None for value,_ in values))
