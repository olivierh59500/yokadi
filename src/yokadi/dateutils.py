# -*- coding: UTF-8 -*-
"""
Date utilities.

@author: Sébastien Renard <sebastien.renard@digitalfox.org>
@license: GPLv3
"""
import time
from datetime import datetime, timedelta

from yokadiexception import YokadiException


def guessDateFormat(tDate):
    """Guess a date format.
    @param tDate: date string like 30/08/2008 or 30/08 or 30
    @return: date format as a string like %d/%m/%Y or %d/%m or %d"""
    if tDate.count("/")==2:
        fDate="%d/%m/%Y"
    elif tDate.count("/")==1:
        fDate="%d/%m"
    else:
        fDate="%d"
    return fDate


def guessTimeFormat(tTime):
    """Guess a time format.
    @param tTime: time string like 12:30:45 or 12:30 or 12
    @return: time format as a string like %H:%M:%S or %H:%M or %H"""
    if tTime.count(":")==2:
        fTime="%H:%M:%S"
    elif tTime.count(":")==1:
        fTime="%H:%M"
    else:
        fTime="%H"
    return fTime


def parseDateTimeDelta(line):
    # FIXME: Do we really want to support float deltas?
    try:
        delta = float(line[:-1])
    except ValueError:
        raise YokadiException("Timeshift must be a float or an integer")

    suffix = line[-1].upper()
    if   suffix == "W":
        return timedelta(days=delta * 7)
    elif suffix == "D":
        return timedelta(days=delta)
    elif suffix == "H":
        return timedelta(hours=delta)
    elif suffix == "M":
        return timedelta(minutes=delta)
    else:
        raise YokadiException("Unable to understand time shift. See help t_set_due")


def parseHumaneDateTime(line):
    """Parse human date and time and return structured datetime object
    Datetime  can be absolute (23/10/2008 10:38) or relative (+5M, +3H, +1D, +6W)
    @param line: human date / time
    @type line: str
    @return: datetime object"""

    # Date & Time format
    fDate=None
    fTime=None

    today=datetime.today().replace(microsecond=0)

    if line.startswith("+"):
        date = today + parseDateTimeDelta(line[1:])
    else:
        date = today
        #Absolute date and/or time
        if " " in line:
            # We assume user give date & time
            tDate, tTime=line.split()
            fDate=guessDateFormat(tDate)
            fTime=guessTimeFormat(tTime)
            try:
                date=datetime(*time.strptime(line, "%s %s" % (fDate, fTime))[0:5])
            except Exception, e:
                raise YokadiException("Unable to understand date & time format:\t%s" % e)
        else:
            if ":" in line:
                fTime=guessTimeFormat(line)
                try:
                    tTime=datetime(*time.strptime(line, fTime)[0:5]).time()
                except ValueError, e:
                    raise YokadiException("Invalid date format: %s" % e)
                date=datetime.combine(today, tTime)
            else:
                fDate=guessDateFormat(line)
                try:
                    date=datetime(*time.strptime(line, fDate)[0:5])
                except ValueError, e:
                    raise YokadiException("Invalid date format: %s" % e)
        if fDate:
            # Set year and/or month to current date if not given
            try:
                if not "%Y" in fDate:
                    date=date.replace(year=today.year)
                if not "%m" in fDate:
                    date=date.replace(month=today.month)
            except ValueError, e:
                    raise YokadiException("Invalid date format: %s" % e)
    return date


def formatTimeDelta(delta):
    """Friendly format a time delta:
        - Show only days if delta > 1 day
        - Show only hours and minutes othewise
    @param timeLeft: Remaining time
    @type timeLeft: timedelta (from datetime)
    @return: formated  str"""
    if delta.days > 7:
        value = "%dw" % (delta.days / 7)
        days = delta.days % 7
        if days > 0:
            value = value + ", %dd" % days
    elif delta.days > 0:
        value = "%dd" % delta.days
    else:
        minutes = delta.seconds / 60
        hours = minutes / 60
        minutes = minutes % 60
        if hours > 0:
            value = "%dh " % hours
        else:
            value = ""
        value = value + "%dm" % minutes
    if delta < timedelta(0):
        value = "-" + value
    return value
# vi: ts=4 sw=4 et