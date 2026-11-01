import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agents import router
from agents.book_agent import (
    BookAgent,
    _idf_table,
    _navigation_chunk,
    _page_anchors,
    _page_supports,
    _tokens,
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

    def test_other_irrational_numbers_do_not_receive_the_sqrt_two_proof(self):
        self.assertIsNone(self.agent.answer("Prove that pi is irrational."))

    def test_programming_cases_do_not_receive_a_parity_template(self):
        self.assertIsNone(self.agent.answer("Explain cases in Python programming."))

    def test_spoken_arithmetic_runs_before_books(self):
        with patch.object(router, "_independent_agent", None), patch.object(router, "_book_agent", self.agent):
            added = router.answer_question(
                "if a number is added by 8 and becomes 9 what is that number?",
                username="John",
            )
            multiplied = router.answer_question(
                "if a number is multiplied by 7 and becomes 9 what is that number?",
                username="John",
            )
            expression = router.answer_question("8-9*/3", username="John")
        self.assertIn("n = 9 - 8", added["response"])
        self.assertIn("= 1", added["response"])
        self.assertNotIn("closest matching evidence", added["response"])
        self.assertIn("9/7", multiplied["response"])
        self.assertNotIn("closest matching evidence", multiplied["response"])
        self.assertIn("couldn't evaluate that math", expression["response"])
        self.assertNotIn("couldn’t find enough support", expression["response"])

    def test_efatha_questions_use_saved_facts(self):
        independent = SimpleNamespace(trained_knowledge=[
            {
                "keywords": ["who is efatha rutakaza", "efatha rutakaza"],
                "response": "Efatha Rutakaza is a software engineer and web developer.",
            },
            {
                "keywords": ["efatha"],
                "response": "Efatha Rutakaza created e-Chat.",
            },
        ])
        with patch.object(router, "_independent_agent", independent), patch.object(router, "_book_agent", self.agent):
            short = router.answer_question("who is efatha?", username="John")
            full = router.answer_question("who is efatha rutakaza?", username="John")
        self.assertIn("created e-Chat", short["response"])
        self.assertIn("software engineer", full["response"])
        self.assertNotIn("Wikipedia definition", short["response"])

    def test_yes_and_no_follow_the_previous_reply(self):
        with patch.object(router, "_independent_agent", None), patch.object(router, "_book_agent", self.agent):
            confirmed = router.answer_question(
                "yeah",
                username="John",
                history=["what is my name?"],
                conversation=[
                    {"role": "user", "content": "what is my name?"},
                    {"role": "assistant", "content": "😊 Your name is John, right?"},
                    {"role": "user", "content": "yeah"},
                ],
            )
            declined = router.answer_question(
                "no",
                username="John",
                history=["what is my name?", "yeah"],
                conversation=[
                    {"role": "assistant", "content": "Okay — tell me about your name."},
                    {"role": "user", "content": "no"},
                ],
            )
        self.assertIn("I'll keep calling you John", confirmed["response"])
        self.assertNotIn("tell me about your name", confirmed["response"])
        self.assertIn("I won’t guess", declined["response"])
        noted = router.answer_question(
            "good",
            username="John",
            conversation=[
                {"role": "assistant", "content": "😄 Great, I’ve got it — your favorite actor is Jackie Chan. I’ll remember that."},
                {"role": "user", "content": "good"},
            ],
        )
        self.assertIn("Understood — yes", noted["response"])
        self.assertNotIn("couldn’t find enough support", declined["response"])

    def test_greeting_and_name_use_the_saved_user(self):
        with patch.object(router, "_independent_agent", None), patch.object(router, "_book_agent", self.agent):
            hello = router.answer_question("hello", username="John")
            name = router.answer_question("what is my name?", username="John")
            who = router.answer_question("who am I?", username="John")
        self.assertIn("👋😄 Hello John!", hello["response"])
        self.assertIn("😊 Your name is John, right?", name["response"])
        self.assertIn("😊 Your name is John, right?", who["response"])
        self.assertNotIn("closest matching evidence", name["response"])

    def test_plain_definitions_do_not_fall_through_to_books(self):
        with (
            patch.object(router, "_independent_agent", None),
            patch.object(router, "_book_agent", self.agent),
            patch.object(router, "wikipedia_definition", return_value=None),
        ):
            result = router.answer_question("what is smart?", username="John")
        self.assertNotIn("closest matching evidence", result["response"])
        self.assertIn("Wikipedia", result["response"])

    def test_definition_questions_go_directly_to_wikipedia(self):
        independent = SimpleNamespace(word_meanings={"python": "Python is a programming language."})
        with (
            patch.object(router, "_independent_agent", independent),
            patch.object(router, "_book_agent", self.agent),
            patch.object(
                router,
                "wikipedia_definition",
                return_value="Wikipedia — Artificial intelligence\nAI is the study of intelligent machines.",
            ) as wiki,
        ):
            result = router.answer_question("what is ai?", username="John")
        wiki.assert_called_once_with("ai", "what is ai?")
        self.assertEqual(result["provider"], "wikipedia")
        self.assertIn("Artificial intelligence", result["response"])
        self.assertNotIn("programming language", result["response"])
        self.assertNotIn("won’t invent", result["response"])

    def test_reflective_questions_use_wikipedia_before_books(self):
        with (
            patch.object(router, "_independent_agent", None),
            patch.object(router, "_book_agent", self.agent),
            patch.object(
                router,
                "search_result_text",
                return_value="Search result:\nGravity. Gravity is a force.",
            ) as search,
        ):
            result = router.answer_question(
                "Suppose that gravity stopped for one minute.",
                username="John",
            )
        search.assert_called_once()
        self.assertEqual(result["provider"], "wikipedia")
        self.assertIn("Gravity", result["response"])
        self.assertNotIn("closest matching evidence", result["response"])

    def test_greeting_and_daily_plans_are_conversation_not_book_excerpts(self):
        with (
            patch.object(router, "_independent_agent", None),
            patch.object(router, "_book_agent", self.agent),
        ):
            hello = router.answer_question("hello", username="John")
            plans = router.answer_question(
                "what have you planned today?", username="John"
            )
        self.assertIn("Hello John", hello["response"])
        self.assertNotIn("closest matching evidence", hello["response"])
        self.assertIn("personal schedule", plans["response"])
        self.assertNotIn("closest matching evidence", plans["response"])
        self.assertIsNone(self.agent.answer("hello"))
        self.assertIsNone(self.agent.answer("what have you planned today?"))

    def test_unrelated_real_world_question_does_not_use_weak_book_evidence(self):
        with (
            patch.object(router, "_independent_agent", None),
            patch.object(router, "_book_agent", self.agent),
        ):
            result = router.answer_question(
                "Why did sales decline in our Kampala shop last month?"
            )
        self.assertNotIn("From the books", result["response"])
        self.assertNotIn("closest matching evidence", result["response"])

    def test_unknown_theorem_does_not_get_a_fake_proof_template(self):
        with (
            patch.object(router, "_independent_agent", None),
            patch.object(router, "_book_agent", self.agent),
        ):
            result = router.answer_question("Prove Fermat's Last Theorem.")
        self.assertIn("checked local derivation", result["response"])
        self.assertNotIn("Given. Write the hypotheses", result["response"])

    def test_router_returns_specific_proof_before_generic_reasoning(self):
        independent = SimpleNamespace(
            confident_answer=lambda *_args, **_kwargs: "Incorrect word-definition fallback"
        )
        with (
            patch.object(router, "_independent_agent", independent),
            patch.object(router, "_book_agent", self.agent),
        ):
            result = router.answer_question("Why is odd + odd always even?")
        self.assertIn("2(m + n + 1)", result["response"])
        self.assertNotIn("Incorrect word-definition fallback", result["response"])

    def test_unsupported_comparison_abstains_instead_of_filling_generic_sections(self):
        with (
            patch.object(router, "_independent_agent", None),
            patch.object(
                router,
                "_book_agent",
                SimpleNamespace(answer=lambda _question: self.fail(
                    "Comparison questions must not fall through to book retrieval"
                )),
            ),
            patch.object(router, "wikipedia_summary", return_value=None),
        ):
            result = router.answer_question(
                "What is the difference between Python and Java?"
            )
        self.assertEqual(result["source"], "independent")
        self.assertIn("reliable source information for both sides", result["response"])
        self.assertNotIn("- Advantages:", result["response"])
        self.assertNotIn("Incorrect local fallback", result["response"])

    def test_comparison_does_not_fall_back_to_irrelevant_book_excerpts(self):
        books = SimpleNamespace(answer=lambda _question: self.fail(
            "Comparison questions must not retrieve unrelated book passages"
        ))
        with (
            patch.object(router, "_independent_agent", None),
            patch.object(router, "_book_agent", books),
            patch.object(router, "wikipedia_summary", return_value=None),
        ):
            result = router.answer_question(
                "What is the difference between music and art?"
            )

        self.assertIn("reliable source information for both sides", result["response"])
        self.assertNotIn("Bayesian", result["response"])
        self.assertNotIn("Convex Optimization", result["response"])

    def test_comparison_uses_wikipedia_notes_for_both_terms(self):
        notes = {
            "python": (
                "Wikipedia — Python\n"
                "Python is a high-level programming language. "
                "Python emphasizes readability and has dynamic typing. "
                "Python has a large standard library."
            ),
            "java": (
                "Wikipedia — Java\n"
                "Java is a high-level programming language. "
                "Java uses static typing and compiles source into bytecode. "
                "Java runs on the Java Virtual Machine."
            ),
        }
        with (
            patch.object(router, "_independent_agent", None),
            patch.object(router, "_book_agent", self.agent),
            patch.object(router, "wikipedia_summary", side_effect=lambda term, _question: notes[term]),
        ):
            result = router.answer_question(
                "What is the difference between Python and Java?"
            )

        self.assertEqual(result["source"], "pattern")
        self.assertEqual(result["provider"], "wikipedia+reasoning-pattern")
        self.assertIn("dynamic typing", result["response"])
        self.assertIn("static typing", result["response"])
        self.assertIn("Sources used for this comparison:", result["response"])
        self.assertIn("[Wikipedia: Python](https://en.wikipedia.org/wiki/Python)", result["response"])
        self.assertIn("[Wikipedia: Java](https://en.wikipedia.org/wiki/Java)", result["response"])
        sources = result["response"].split("Sources used for this comparison:", 1)[1]
        self.assertNotIn("high-level programming language", sources)

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

    def test_valid_sound_comparison_uses_local_rule(self):
        with (
            patch.object(router, "_independent_agent", None),
            patch.object(router, "_book_agent", self.agent),
        ):
            result = router.answer_question(
                "What’s the difference between a valid argument and a sound argument?"
            )
        self.assertEqual(result["source"], "pattern")
        self.assertIn("Every sound argument is valid", result["response"])
        self.assertNotIn("not sure", result["response"].lower())

    def test_semantic_book_search_finds_paraphrased_local_evidence(self):
        examples = (
            (
                "Linear Algebra",
                128,
                "A basis for a vector space is a linearly independent set that spans "
                "the space. Every vector has a unique representation using coordinates "
                "with respect to that basis.",
                "How do I know each vector has one coordinate representation?",
            ),
            (
                "Linear Algebra",
                207,
                "The rank-nullity theorem states that the dimension of the domain "
                "equals the rank of the image plus the nullity of the kernel.",
                "How does the dimension split between the image and kernel?",
            ),
            (
                "Introductory Statistics",
                71,
                "A confidence interval estimates a population parameter from a sample "
                "and is reported with a chosen confidence level.",
                "How do samples give a range for an unknown population value?",
            ),
            (
                "Think Python",
                99,
                "A for loop iterates over each item in a sequence such as a list or "
                "range, executing the loop body for every element.",
                "How can Python repeat an action for each item in a list?",
            ),
            (
                "Think Bayes",
                36,
                "Bayes' rule updates a prior probability using evidence and likelihood "
                "to produce a posterior probability.",
                "How does evidence update what I believed beforehand?",
            ),
        )
        chunks = [
            {"text": passage, "tokens": _tokens(passage), "page": page}
            for _title, page, passage, _question in examples
        ]
        self.agent.books = [
            {"title": title, "chunks": [chunk]}
            for (title, _page, _passage, _question), chunk in zip(examples, chunks)
        ]
        self.agent._idf = _idf_table(self.agent.books)

        for title, page, _passage, question in examples:
            with self.subTest(question=question):
                matches = self.agent._from_each_book(question)
                self.assertTrue(matches, f"No local evidence retrieved for {question}")
                self.assertEqual(matches[0][0], title)
                self.assertEqual(matches[0][1], page)

    def test_book_answer_includes_verifiable_title_and_page(self):
        passage = (
            "A basis for a vector space is a linearly independent set that spans "
            "the space. Every vector has a unique representation using coordinates "
            "with respect to that basis."
        )
        self.agent.books = [{
            "title": "Linear Algebra",
            "chunks": [{
                "text": passage,
                "tokens": _tokens(passage),
                "page": 128,
            }],
        }]
        self.agent._idf = _idf_table(self.agent.books)

        result = self.agent.answer(
            "How do I know each vector has one coordinate representation?"
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["source"], "book")
        self.assertIn("_Linear Algebra, p. 128_", result["response"])
        self.assertIn("unique representation", result["response"])

    def test_comparison_without_local_evidence_does_not_invent_a_summary(self):
        result = self.agent.answer(
            "What is the difference between prior and posterior probability?"
        )
        self.assertIsNone(result)

    def test_comparison_requires_evidence_for_both_sides(self):
        passage = (
            "Python is a general-purpose programming language with readable syntax "
            "and a large standard library."
        )
        self.agent.books = [{
            "title": "Think Python",
            "chunks": [{
                "text": passage,
                "tokens": _tokens(passage),
                "page": 1,
            }],
        }]
        self.agent._idf = _idf_table(self.agent.books)

        self.assertEqual(
            self.agent._from_each_book(
                "What is the difference between Python and Java?"
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
