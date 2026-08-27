import json
import logging
import unittest
from collections.abc import Sequence

from classifier import (
    Classification,
    ClassificationBatch,
    DeferredClassification,
    JsonFormatter,
    PaperlessDocument,
    Taxonomy,
    TaxonomyItem,
    apply_classifications,
    normalize_base_url,
    normalize_page_url,
    sanitize_content,
    validate_batch,
)


class JsonFormatterTest(unittest.TestCase):
    def test_emits_one_line_structured_log(self) -> None:
        record = logging.LogRecord(
            "paperless-classifier",
            logging.WARNING,
            __file__,
            1,
            "classified %s",
            ("document\n42",),
            None,
        )

        output = JsonFormatter().format(record)
        payload = json.loads(output)

        self.assertNotIn("\n", output)
        self.assertEqual(payload["level"], "warning")
        self.assertEqual(payload["logger"], "paperless-classifier")
        self.assertEqual(payload["message"], "classified document\n42")
        self.assertRegex(payload["timestamp"], r"^\d{4}-\d{2}-\d{2}T.*Z$")


class ValidateBatchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.taxonomy = Taxonomy(
            correspondents=(TaxonomyItem(id=1, name="IRS"),),
            document_types=(TaxonomyItem(id=2, name="Tax Form"),),
            tags=(TaxonomyItem(id=3, name="financial"),),
            inbox_tag_id=4,
        )

    def classification(self, document_id: int) -> Classification:
        return Classification(
            kind="classification",
            document_id=document_id,
            correspondent="IRS",
            document_type="Tax Form",
            tags=("financial",),
            title="W-2 Wage and Tax Statement (2025)",
        )

    def test_accepts_one_decision_per_document(self) -> None:
        batch = ClassificationBatch(decisions=(self.classification(10),))

        result = validate_batch(batch, {10}, self.taxonomy, allow_deferred=True)

        self.assertEqual(result, batch)

    def test_rejects_missing_and_unexpected_documents(self) -> None:
        batch = ClassificationBatch(decisions=(self.classification(11),))

        with self.assertRaisesRegex(ValueError, "missing.*10.*unexpected.*11"):
            validate_batch(batch, {10}, self.taxonomy, allow_deferred=True)

    def test_rejects_duplicate_documents(self) -> None:
        batch = ClassificationBatch(
            decisions=(self.classification(10), self.classification(10))
        )

        with self.assertRaisesRegex(ValueError, "duplicate document IDs: 10"):
            validate_batch(batch, {10}, self.taxonomy, allow_deferred=True)

    def test_rejects_deferral_after_full_content(self) -> None:
        batch = ClassificationBatch(
            decisions=(
                DeferredClassification(
                    kind="needs_full_content",
                    document_id=10,
                    reason="Issuer is outside the compact excerpt.",
                ),
            )
        )

        with self.assertRaisesRegex(
            ValueError, "full-content documents must be classified"
        ):
            validate_batch(batch, {10}, self.taxonomy, allow_deferred=False)

    def test_rejects_new_types_above_cap(self) -> None:
        taxonomy = self.taxonomy.model_copy(
            update={
                "document_types": tuple(
                    TaxonomyItem(id=index, name=f"Type {index}")
                    for index in range(1, 26)
                )
            }
        )
        classification = self.classification(10).model_copy(
            update={"document_type": "New Type"}
        )
        batch = ClassificationBatch(decisions=(classification,))

        with self.assertRaisesRegex(ValueError, "document type cap"):
            validate_batch(batch, {10}, taxonomy, allow_deferred=True)

    def test_rejects_new_tags_above_cap(self) -> None:
        taxonomy = self.taxonomy.model_copy(
            update={
                "tags": tuple(
                    TaxonomyItem(id=index, name=f"tag-{index}")
                    for index in range(1, 21)
                )
            }
        )
        classification = self.classification(10).model_copy(
            update={"tags": ("new-tag",)}
        )
        batch = ClassificationBatch(decisions=(classification,))

        with self.assertRaisesRegex(ValueError, "tag cap"):
            validate_batch(batch, {10}, taxonomy, allow_deferred=True)

    def test_rejects_uppercase_new_tag(self) -> None:
        classification = self.classification(10).model_copy(update={"tags": ("Home",)})
        batch = ClassificationBatch(decisions=(classification,))

        with self.assertRaisesRegex(ValueError, "lowercase words"):
            validate_batch(batch, {10}, self.taxonomy, allow_deferred=True)


class SanitizeContentTest(unittest.TestCase):
    def test_normalizes_ocr_noise(self) -> None:
        content = "Invoice\x00  text_____\n\n\n\nTotal"

        self.assertEqual(sanitize_content(content), "Invoice text\n\nTotal")


class NormalizePageUrlTest(unittest.TestCase):
    def test_rejects_bare_host(self) -> None:
        with self.assertRaisesRegex(ValueError, "HTTP or HTTPS"):
            normalize_base_url("paperless.example")

    def test_preserves_base_scheme_for_same_host(self) -> None:
        result = normalize_page_url(
            "http://paperless.example/api/documents/?page=2",
            expected_host="paperless.example",
        )

        self.assertEqual(result, "api/documents/?page=2")

    def test_rejects_pagination_to_another_host(self) -> None:
        with self.assertRaisesRegex(ValueError, "unexpected host"):
            normalize_page_url(
                "https://attacker.example/api/documents/?page=2",
                expected_host="paperless.example",
            )


class FakePaperlessClient:
    def __init__(self, document: PaperlessDocument) -> None:
        self.document = document
        self.update: dict[str, object] | None = None

    async def get_document(self, document_id: int) -> PaperlessDocument:
        if document_id != self.document.id:
            raise AssertionError(f"unexpected document ID: {document_id}")
        return self.document

    async def create_taxonomy_item(self, path: str, name: str) -> TaxonomyItem:
        raise AssertionError(f"unexpected taxonomy creation: {path}/{name}")

    async def create_tag(self, name: str, *, is_inbox: bool = False) -> TaxonomyItem:
        raise AssertionError(f"unexpected tag creation: {name}/{is_inbox}")

    async def update_document(
        self,
        document_id: int,
        *,
        title: str,
        correspondent_id: int,
        document_type_id: int,
        tag_ids: Sequence[int],
    ) -> None:
        self.update = {
            "document_id": document_id,
            "title": title,
            "correspondent_id": correspondent_id,
            "document_type_id": document_type_id,
            "tag_ids": list(tag_ids),
        }


class ApplyClassificationsTest(unittest.IsolatedAsyncioTestCase):
    async def test_updates_all_fields_and_removes_inbox_tag(self) -> None:
        taxonomy = Taxonomy(
            correspondents=(TaxonomyItem(id=1, name="IRS"),),
            document_types=(TaxonomyItem(id=2, name="Tax Form"),),
            tags=(TaxonomyItem(id=3, name="financial"),),
            inbox_tag_id=4,
        )
        client = FakePaperlessClient(
            PaperlessDocument(id=10, title="scan", tags=(3, 4))
        )
        classification = Classification(
            kind="classification",
            document_id=10,
            correspondent="IRS",
            document_type="Tax Form",
            tags=("financial",),
            title="W-2 Wage and Tax Statement (2025)",
        )

        result = await apply_classifications(client, (classification,), taxonomy)

        self.assertEqual(result, (1, 0))
        self.assertEqual(
            client.update,
            {
                "document_id": 10,
                "title": "W-2 Wage and Tax Statement (2025)",
                "correspondent_id": 1,
                "document_type_id": 2,
                "tag_ids": [3],
            },
        )

    async def test_does_not_overwrite_document_that_left_inbox(self) -> None:
        taxonomy = Taxonomy(
            correspondents=(TaxonomyItem(id=1, name="IRS"),),
            document_types=(TaxonomyItem(id=2, name="Tax Form"),),
            tags=(TaxonomyItem(id=3, name="financial"),),
            inbox_tag_id=4,
        )
        client = FakePaperlessClient(
            PaperlessDocument(id=10, title="already classified", tags=(3,))
        )
        classification = Classification(
            kind="classification",
            document_id=10,
            correspondent="IRS",
            document_type="Tax Form",
            tags=("financial",),
            title="W-2 Wage and Tax Statement (2025)",
        )

        result = await apply_classifications(client, (classification,), taxonomy)

        self.assertEqual(result, (0, 1))
        self.assertIsNone(client.update)


if __name__ == "__main__":
    unittest.main()
