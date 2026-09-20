"""Scalar-only choices for browser-local trip card rendering."""
import time

from .usage_events import UsageEvents
from .usage_reports import period_window


class TripCards:
    def __init__(self,database,clock=None):
        self.events=UsageEvents(database)
        self.clock=clock or (lambda:int(time.time()*1000))

    def query(self,vehicle,date):
        window=period_window('month',date);now=self.clock()
        found=self.events.between(vehicle,window['start'],window['end'])
        events=[row for row in found['events'] if row['end_time']<=now]
        return dict(window=window,as_of=now,trips=[r for r in events if r['kind']=='trip_end'],
                    charges=[r for r in events if r['kind']=='charge_end'])
