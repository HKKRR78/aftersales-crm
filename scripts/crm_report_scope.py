"""Explicit rolling release scope, separate from retained source history."""
from datetime import date,datetime,timedelta,timezone
from crm_report_model import sunday

SHANGHAI=timezone(timedelta(hours=8))


def recent_release_scope(as_of):
    week=sunday(as_of)
    displayed=[week-timedelta(weeks=n) for n in range(5,0,-1)]
    # Selecting any of the five released weeks keeps the existing product
    # table's five historical columns and its preceding comparison week.
    # Therefore the earliest selection needs five additional complete weeks.
    required_start=displayed[0]-timedelta(weeks=5)
    periods=[dict(start=str(day),end=str(day+timedelta(days=7)),kind='complete')
             for day in (required_start+timedelta(weeks=n) for n in range(10))]
    elapsed=(as_of-week).days
    if elapsed:
        periods.extend(dict(start=str(start),end=str(start+timedelta(days=elapsed)),kind='progress')
                       for start in (week-timedelta(days=7),week))
    return dict(kind='recent_five_complete_weeks',timezone='Asia/Shanghai',weekStartsOn='Sunday',
                asOf=str(as_of),displayStart=str(displayed[0]),displayEnd=str(week),
                selectableReleaseWeeks=[str(day) for day in displayed],
                requiredStart=str(required_start),requiredEnd=str(as_of),requiredPeriods=periods)


def validate_release_scope(scope,start,end):
    expected=recent_release_scope(end)
    if scope!=expected or str(start)!=expected['requiredStart']:
        raise ValueError('release scope does not cover the five selected weeks and every required comparison')
    return expected


if __name__=='__main__':
    import argparse,json
    p=argparse.ArgumentParser();p.add_argument('--as-of',type=date.fromisoformat,default=datetime.now(SHANGHAI).date())
    print(json.dumps(recent_release_scope(p.parse_args().as_of),ensure_ascii=False))
