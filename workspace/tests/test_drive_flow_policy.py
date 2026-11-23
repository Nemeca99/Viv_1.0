import pytest

from autonomy.drive_flow_policy import DriveFlowDenied, authorize_transfer


def test_archive_flows_are_allowed():
    assert authorize_transfer(r"L:\work", r"D:\stage")["allowed"]
    assert authorize_transfer(r"D:\stage", r"F:\archive")["allowed"]
    assert authorize_transfer(r"D:\stage", r"G:\cloud")["allowed"]


def test_sandbox_only_exports_to_l():
    assert authorize_transfer(r"E:\sandbox", r"L:\import")["allowed"]
    with pytest.raises(DriveFlowDenied):
        authorize_transfer(r"E:\sandbox", r"D:\stage")
    with pytest.raises(DriveFlowDenied):
        authorize_transfer(r"E:\sandbox", r"G:\cloud")


def test_d_to_l_requires_architect_approval():
    with pytest.raises(DriveFlowDenied):
        authorize_transfer(r"D:\stage", r"L:\restore")
    assert authorize_transfer(
        r"D:\stage", r"L:\restore", architect_approved=True
    )["reason"] == "architect_approved_restore"
