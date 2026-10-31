import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agents import router
from agents.book_agent import (
    BookAgent,
    _navigation_chunk,
    _page_anchors,
    _page_supports,
)
from agents.reasoning_patterns import pattern_answer


class ReasoningScorecardTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.agent = BookAgent(Path(self.temp_dir.name))

    def tearDown(self):
        self.temp_dir.cleanup()

    def answer(self, question):
        result = self.agent.answer(question)
        self.assertIsNotNone(result, f"Expected a local proof for: {question}")
        return result["response"]

    def test_sqrt_two_proof_uses_contradiction(self):
        answer = self.answer("Prove that the square root of 2 is irrational")
        self.assertIn("coprime positive integers", answer)
        self.assertIn("b is even", answer)
        self.assertIn("contradicting", answer)

    def test_even_sum_proof_uses_even_definition(self):
        answer = self.answer("Prove the sum of two even integers is even")
        self.assertIn("a + b = 2m + 2n", answer)
        self.assertIn("m + n is an integer", answer)

    def test_odd_sum_proof_is_not_confused_with_even_sum(self):
        answer = self.answer("Show that the sum of two odd integers is even")
        self.assertIn("a = 2m + 1", answer)
        self.assertIn("2(m + n + 1)", answer)
        self.assertNotIn("a = 2m and b = 2n", answer)

    def test_even_square_proof_uses_square_algebra(self):
        answer = self.answer("Show that if n is even then n squared is even")
        self.assertIn("n = 2k", answer)
        self.assertIn("n² = (2k)²", answer)
        self.assertNotIn("sum of two even", answer)

    def test_odd_square_proof_uses_square_algebra(self):
        answer = self.answer("Prove the square of an odd integer is odd")
        self.assertIn("n = 2k + 1", answer)
        self.assertIn("2(2k² + 2k) + 1", answer)

    def test_odd_plus_odd_paraphrase_is_understood(self):
        answer = self.answer("Why is odd + odd always even?")
        self.assertIn("sum of two odd integers is even", answer)

    def test_even_plus_odd_proof_has_odd_result(self):
        answer = self.answer("Prove that adding an even and an odd integer gives an odd integer")
        self.assertIn("2m + 2n + 1", answer)
        self.assertIn("so the sum is odd", answer)

    def test_false_odd_sum_claim_gets_counterexample(self):
        answer = self.answer("Is the sum of two odd integers always odd?")
        self.assertIn("claim is false", answer)
        self.assertIn("1 + 1 = 2", answer)

    def test_false_even_square_claim_gets_counterexample(self):
        answer = self.answer("Is the square of an even integer odd?")
        self.assertIn("claim is false", answer)
        self.assertIn("n = 2", answer)
        self.assertIn("n² = 4", answer)

    def test_odd_product_proof_uses_factorization(self):
        answer = self.answer("Prove the product of two odd integers is odd")
        self.assertIn("(2m + 1)(2n + 1)", answer)
        self.assertIn("so the product is odd", answer)

    def test_even_product_proof_uses_even_factor(self):
        answer = self.answer("Explain why the product of an even and an odd integer is even")
        self.assertIn("(2m)n = 2(mn)", answer)
        self.assertIn("the product is even", answer)

    def test_false_odd_product_claim_gets_counterexample(self):
        answer = self.answer("Is the product of two odd integers even?")
        self.assertIn("claim is false", answer)
        self.assertIn("3 × 5 = 15", answer)

    def test_unknown_theorem_does_not_get_a_fake_proof_template(self):
        api = SimpleNamespace(retrieve=lambda *_args, **_kwargs: None)
        with (
            patch.object(router, "_independent_agent", None),
            patch.object(router, "_api_agent", api),
            patch.object(router, "_book_agent", self.agent),
            patch.object(router, "wikipedia_summary", return_value=None),
            patch.object(router, "ollama_answer", return_value=None),
        ):
            result = router.answer_question("Prove Fermat's Last Theorem.")
        self.assertIn("checked local derivation", result["response"])
        self.assertNotIn("Given. Write the hypotheses", result["response"])

    def test_router_returns_specific_proof_before_generic_reasoning(self):
        api = SimpleNamespace(retrieve=lambda *_args, **_kwargs: None)
        independent = SimpleNamespace(
            confident_answer=lambda *_args, **_kwargs: "Incorrect word-definition fallback"
        )
        with (
            patch.object(router, "_independent_agent", independent),
            patch.object(router, "_api_agent", api),
            patch.object(router, "_book_agent", self.agent),
            patch.object(router, "wikipedia_summary", return_value=None),
            patch.object(router, "ollama_answer", return_value=None),
        ):
            result = router.answer_question("Why is odd + odd always even?")
        self.assertIn("2(m + n + 1)", result["response"])
        self.assertNotIn("Incorrect word-definition fallback", result["response"])

    def test_difference_of_definitions_uses_live_wikipedia_comparison(self):
        questions = (
            "What is the difference of Python and Java?",
            "What is the difference between Python and Java?",
        )
        api = SimpleNamespace(retrieve=lambda *_args, **_kwargs: None)
        independent = SimpleNamespace(
            confident_answer=lambda *_args, **_kwargs: "Incorrect local fallback"
        )
        books = SimpleNamespace(
            answer=lambda *_args, **_kwargs: self.fail(
                "Definition comparisons must use the live-Wikipedia formatter first"
            )
        )

        for question in questions:
            with self.subTest(question=question):
                def wikipedia_note(term, _question):
                    notes = {
                        "python": (
                            "Wikipedia — Python\n"
                            "Python is a high-level, general-purpose programming language. "
                            "It emphasizes readability."
                        ),
                        "java": (
                            "Wikipedia — Java\n"
                            "Java is a class-based, object-oriented programming language. "
                            "It runs on a virtual machine."
                        ),
                    }
                    return notes.get(term.lower())

                with (
                    patch.object(router, "_independent_agent", independent),
                    patch.object(router, "_api_agent", api),
                    patch.object(router, "_book_agent", books),
                    patch.object(router, "wikipedia_summary", side_effect=wikipedia_note) as wiki,
                ):
                    result = router.answer_question(question)

                self.assertEqual(result["source"], "pattern")
                self.assertEqual(result["provider"], "reasoning-pattern")
                self.assertEqual(
                    [call.args[0] for call in wiki.call_args_list],
                    ["python", "java"],
                )
                self.assertIn("Python is a high-level", result["response"])
                self.assertIn("Java is a class-based", result["response"])
                self.assertIn("- What they are:\n  - *Python*:", result["response"])
                self.assertIn("- Advantages:\n  - *Python*:", result["response"])
                self.assertIn("\n\n- Limitations:\n  - *Python*:", result["response"])
                self.assertIn("\n\nSources used for this comparison:\n- python:", result["response"])
                self.assertIn("Sources used for this comparison:", result["response"])

    def test_sqrt_two_citation_requires_specific_supporting_evidence(self):
        anchors = _page_anchors("Prove that the square root of 2 is irrational")
        relevant = (
            "For sqrt(2), assume it is rational and write the fraction in "
            "lowest terms; then numerator and denominator are both even."
        )
        unrelated = (
            "A proof by contradiction is an ancient method used to prove "
            "that certain numbers are irrational."
        )
        self.assertTrue(_page_supports(relevant, "sqrt(2) irrational lowest terms", anchors))
        self.assertFalse(_page_supports(unrelated, "sqrt(2) irrational lowest terms", anchors))

    def test_table_of_contents_is_not_used_as_a_reasoning_citation(self):
        table_of_contents = (
            "4.1. Theorems 113 4.2. Definitions 115 4.3. Direct Proof 118 "
            "4.4. Using Cases 124 4.5. Contrapositive Proof 128"
        )
        self.assertTrue(_navigation_chunk(table_of_contents))
        index_page = (
            "null space, 411, range space, 411, codomain, A-7, cofactor, 354, "
            "column, 15, rank, 129, basis, 135, vector, 16"
        )
        self.assertTrue(_navigation_chunk(index_page))

    def test_parity_proof_does_not_cite_unrelated_book_matches(self):
        question = "Why is odd + odd always even?"
        self.agent.books = [{
            "title": "Linear Algebra",
            "chunks": [{
                "text": "Solutions to Exercises. One way to decide even versus odd is to count rows.",
                "tokens": set(),
                "page": 34,
            }],
        }]
        self.assertEqual(self.agent._from_each_book(question), [])

    def test_induction_proves_the_identity_that_was_asked(self):
        answer = self.answer(
            "Prove by induction that 1 + 2 + … + n = n(n+1)/2."
        )
        self.assertIn("Base case (n = 1)", answer)
        self.assertIn("Inductive hypothesis", answer)
        self.assertIn("(k + 1)(k + 2)/2", answer)
        self.assertIn("holds for every integer n ≥ 1", answer)
        self.assertNotIn("From the books:", answer)

    def test_induction_does_not_substitute_a_different_formula(self):
        answer = self.answer(
            "Prove by induction that 6 + 3 + … + n = n(n+8)/1."
        )
        self.assertIn("verify this induction claim as written", answer)
        self.assertIn("exact sequence", answer)
        self.assertNotIn("n(n + 1)/2", answer)
        self.assertNotIn("Base case", answer)

    def test_unspecified_induction_claim_asks_for_the_proposition(self):
        answer = self.answer("Explain how to prove this by induction.")
        self.assertIn("state the exact proposition P(n)", answer)

    def test_conditional_is_false_only_for_true_p_and_false_q(self):
        answer = self.answer("When is P → Q false?")
        self.assertIn("P is true and Q is false", answer)
        self.assertIn("implication is true", answer)

    def test_subset_example_includes_a_counterexample(self):
        answer = self.answer("Give an example of subsets")
        self.assertIn("{1, 2} ⊆ {1, 2, 3}", answer)
        self.assertIn("{1, 4} ⊄ {1, 2, 3}", answer)
        self.assertIn("4 is missing", answer)

    def test_rank_nullity_defines_each_term(self):
        answer = self.answer("State the rank-nullity theorem and explain each term.")
        self.assertIn("dim(V) = rank(T) + nullity(T)", answer)
        self.assertIn("dim(im(T))", answer)
        self.assertIn("dim(ker(T))", answer)
        self.assertIn("number of columns", answer)

    def test_basis_requires_independence_and_spanning(self):
        answer = self.answer("What makes a set of vectors a basis?")
        self.assertIn("spans the space", answer)
        self.assertIn("linearly independent", answer)
        self.assertIn("unique coordinate", answer)

    def test_convex_set_definition_includes_example_and_nonexample(self):
        answer = self.answer("Define a convex set.")
        self.assertIn("t ∈ [0, 1]", answer)
        self.assertIn("[0, 1] is convex", answer)
        self.assertIn("{0, 1} is not convex", answer)

    def test_valid_and_sound_argument_comparison_is_defined(self):
        result = pattern_answer(
            "What’s the difference between a valid argument and a sound argument?",
            notes={},
        )
        self.assertIsNotNone(result)
        answer = result["response"]
        self.assertIn("conclusion must be true if all the premises are true", answer)
        self.assertIn("valid and also has premises that are actually true", answer)
        self.assertIn("Every sound argument is valid", answer)
        self.assertNotIn("I do not have a source page", answer)

    def test_valid_sound_comparison_still_uses_live_wikipedia_route(self):
        api = SimpleNamespace(retrieve=lambda *_args, **_kwargs: None)
        independent = SimpleNamespace(
            confident_answer=lambda *_args, **_kwargs: "Incorrect local fallback"
        )
        with (
            patch.object(router, "_independent_agent", independent),
            patch.object(router, "_api_agent", api),
            patch.object(router, "_book_agent", self.agent),
            patch.object(router, "wikipedia_summary", return_value=None) as wiki,
        ):
            result = router.answer_question(
                "What’s the difference between a valid argument and a sound argument?"
            )
        self.assertEqual(result["source"], "pattern")
        self.assertEqual(wiki.call_count, 2)
        self.assertIn("Every sound argument is valid", result["response"])
        self.assertNotIn("not sure", result["response"].lower())


if __name__ == "__main__":
    unittest.main()
