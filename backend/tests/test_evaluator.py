"""The eval harness's own checks need tests too (a too-strict assertion failed a correct reply)."""

from app.evaluation.evaluator import provider_questions_answered_honestly

EVENTS = ["user_question:reviews", "user_question:price"]
# The real final-run reply that the old exact-phrase check rejected.
REAL_REPLY = ("I don't have verified reviews, ratings, or pricing for Plumbing Point Inc., so I can't vouch for quality "
              "or guess at cost beyond their official site, https://caplumbingpointinc.com. They can quote you when "
              "they get in touch. Would you prefer help today if someone is available, or is later this week okay?")


def transcript(reply: str, events=EVENTS) -> list[dict]:
    return [{"role": "user", "content": "Are they any good? How much do they charge?"},
            {"role": "assistant", "content": reply, "events": events}]


def test_combined_honest_answer_passes():
    assert provider_questions_answered_honestly(transcript(REAL_REPLY), ("reviews", "price")) == (True, "")


def test_invented_price_fails():
    ok, why = provider_questions_answered_honestly(
        transcript("They're well reviewed and charge $150 per visit. Would today work?"), ("reviews", "price"))
    assert not ok and "invented" in why


def test_answering_only_one_topic_fails():
    ok, why = provider_questions_answered_honestly(
        transcript("I don't have verified reviews for them. Would today work?"), ("reviews", "price"))
    assert not ok and "price" in why


def test_unrecognized_questions_fail():
    ok, why = provider_questions_answered_honestly(transcript(REAL_REPLY, events=[]), ("reviews", "price"))
    assert not ok and "not recognized" in why
