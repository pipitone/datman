#!/usr/bin/env python
from StringIO import StringIO
from nose.tools import *
import datman as dm


def test_load_empty_checklist():
    checklistdata = StringIO()
    checklist = dm.checklist.load(checklistdata)


def test_empty_checklist_is_blacklisted():
    checklist = dm.checklist.load(StringIO())
    assert not checklist.is_blacklisted("stage", "series"), checklist


def test_empty_checklist_blacklist_add_new_stage():
    checklist = dm.checklist.load(StringIO())
    checklist.blacklist("stage", "series")
    assert checklist.is_blacklisted("stage", "series"), checklist


def test_empty_checklist_blacklist_remove_new_stage():
    checklist = dm.checklist.load(StringIO())
    checklist.unblacklist("stage", "series")
    assert not checklist.is_blacklisted("stage", "series"), checklist


def test_add_remove_to_empty_blacklist():
    checklist = dm.checklist.load(StringIO())
    checklist.blacklist("stage", "series")
    checklist.unblacklist("stage", "series")
    assert not checklist.is_blacklisted("stage", "series"), checklist


def test_remove_from_empty_blacklist():
    checklist = dm.checklist.load(StringIO())
    checklist.unblacklist("stage", "series")
    assert not checklist.is_blacklisted("stage", "series"), checklist


def test_save_load_checklist():
    checklist = dm.checklist.load(StringIO())
    checklist.blacklist("stage", "series")

    stream = StringIO()
    checklist.save(stream)
    stream.seek(0)

    checklist = dm.checklist.load(stream)
    assert checklist.is_blacklisted("stage", "series"), checklist

def test_load_empty_doc():
    checklist = dm.checklist.load(StringIO(""))
    assert not checklist.is_blacklisted("stage", "series"), checklist

def test_no_blacklist_key():
    checklist = dm.checklist.load(StringIO(
    """
    ignore: 
    """))
    assert not checklist.is_blacklisted("stage", "series"), checklist

def test_no_blacklist_key_add_entry():
    checklist = dm.checklist.load(StringIO(
    """
    ignore: 
    """))
    checklist.blacklist("stage", "series")
    assert checklist.is_blacklisted("stage", "series"), checklist

@raises(dm.checklist.FormatError)
def test_load_format_error_non_dict_parent():
    checklist = dm.checklist.load(StringIO(
        """
    - blacklist:
    """))

def test_stage_not_listed():
    checklist = dm.checklist.load(StringIO(
    """
    blacklist: {}
    """))
    assert not checklist.is_blacklisted("stage", "series"), checklist

@raises(dm.checklist.FormatError)
def test_stage_is_list():
    checklist = dm.checklist.load(StringIO(
    """
    blacklist:
      - stage: 
        series:
    """))
    assert not checklist.is_blacklisted("stage", "series"), checklist

def test_stage_empty():
    checklist = dm.checklist.load(StringIO(
    """
    blacklist:
      stage: {}
    """))
    assert not checklist.is_blacklisted("stage", "series"), checklist
    checklist.blacklist("stage", "series"), checklist
    assert checklist.is_blacklisted("stage", "series"), checklist

@raises(dm.checklist.FormatError)
def test_stage_value_is_not_dict_blacklist():
    checklist = dm.checklist.load(StringIO(
        """
    blacklist:
      stage:
        - series
    """))
    checklist.blacklist("stage", "series")

@raises(dm.checklist.FormatError)
def test_stage_value_is_not_dict_is_blacklisted():
    checklist = dm.checklist.load(StringIO(
        """
    blacklist:
      stage:
        - series
    """))
    checklist.is_blacklisted("stage", "series")

def test_load_and_blacklist_new_stage():
    checklist = dm.checklist.load(StringIO(
        """
    blacklist:
      stage:
        series1: 
    """))
    checklist.blacklist("stage", "series2")
    assert checklist.is_blacklisted("stage", "series1"), checklist
    assert checklist.is_blacklisted("stage", "series2"), checklist
