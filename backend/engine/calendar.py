from .datetime import add_days, day_of, weekday_of


class Calendar:
    def __init__(self, holidays=(), cutoff_hour=15):
        self.closed = frozenset(holidays)
        self.cutoff_hour = cutoff_hour

    def is_business_day(self, day):
        return weekday_of(day) not in (0, 6) and day not in self.closed

    def next_business_day(self, day):
        next_day = add_days(day, 1)
        while not self.is_business_day(next_day):
            next_day = add_days(next_day, 1)
        return next_day

    def clock_start(self, stamp):
        day = day_of(stamp)
        if not self.is_business_day(day):
            return {"day": self.next_business_day(day), "beforeCutoff": True}
        return {"day": day, "beforeCutoff": stamp.hour < self.cutoff_hour}

    def business_days_between(self, start, end):
        count = 0
        day = add_days(start, 1)
        while day <= end:
            count += int(self.is_business_day(day))
            day = add_days(day, 1)
        return count

    def same_day(self, stamp):
        return self.clock_start(stamp)["day"]

    def next_day(self, stamp):
        return self.next_business_day(self.same_day(stamp))

    def cutoff_rule(self, stamp):
        clock = self.clock_start(stamp)
        return clock["day"] if clock["beforeCutoff"] else self.next_business_day(clock["day"])
