"""Image requests are handled by Neema (photo card), not escalated to a human;
genuine document/file requests still go to a human. Tests the classifier that
gates /api/n8n/escalate.
"""
from app.routers.n8n_bridge import _is_image_request


def test_image_requests_are_recognised():
    assert _is_image_request("Do you have the bread images?")
    assert _is_image_request("do you have bread images?")
    assert _is_image_request("can I see a photo of the cassock?")
    assert _is_image_request("show me the mitre")
    assert _is_image_request("send the pictures please")
    assert _is_image_request("how does it look?")


def test_document_and_non_image_requests_are_not():
    assert not _is_image_request("send me the invoice pdf")      # document → human
    assert not _is_image_request("can you email the brochure?")  # document → human
    assert not _is_image_request("I need the price list pdf")     # document → human
    assert not _is_image_request("I want to buy bread")           # not a media request
    assert not _is_image_request("how much is a mitre?")
    assert not _is_image_request("")
    assert not _is_image_request(None)


def test_ambiguous_photo_plus_document_defers_to_human():
    # A photo AND a document mentioned → let a human handle it.
    assert not _is_image_request("do you have a photo brochure or pdf?")
