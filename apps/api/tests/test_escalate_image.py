"""Photo requests go to Neema (she sends product-photo cards herself);
genuine document/file requests still flip to a human. Tests the LIVE native
classifier (`wa_native._is_doc_request`) that gates the in-process escalation —
the n8n-era `/api/n8n/escalate` route and its `_is_image_request` twin were
removed with the retirement (2026-08-11).
"""
from app.services.wa_native import _is_doc_request


def test_document_requests_are_escalated():
    assert _is_doc_request("send me the invoice pdf")
    assert _is_doc_request("can you email the brochure?")
    assert _is_doc_request("I need the price list pdf")
    assert _is_doc_request("nitumie katalogi")            # Swahili: send the catalogue
    assert _is_doc_request("do you have a photo brochure or pdf?")  # doc wins → human


def test_photo_and_ordinary_requests_stay_with_neema():
    assert not _is_doc_request("Do you have the bread images?")
    assert not _is_doc_request("can I see a photo of the cassock?")
    assert not _is_doc_request("show me the mitre")
    assert not _is_doc_request("send the pictures please")
    assert not _is_doc_request("how does it look?")
    assert not _is_doc_request("I want to buy bread")
    assert not _is_doc_request("how much is a mitre?")
    assert not _is_doc_request("")


def test_mentioning_a_document_without_asking_is_not_escalated():
    # "the receipt you sent" mentions a document but requests nothing.
    assert not _is_doc_request("thank you for the invoice")
