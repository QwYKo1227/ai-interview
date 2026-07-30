# AI Interview

This context schedules and conducts interviews, preserves interview evidence, produces AI analysis, collects human reviews, and records the final interview decision.

## Language

**Interview**:
A scheduled candidate evaluation session whose lifecycle runs from scheduling through its actual end.
_Avoid_: Recording, assessment, review

**Recording Session**:
The single active capture of interview audio, owned by one assigned interviewer and composed of ordered recording chunks.
_Avoid_: Full audio, recorder lock

**Recording Owner**:
The assigned interviewer who currently holds responsibility for capturing and ending the Recording Session.
_Avoid_: First interviewer, primary panel member

**Interview Note**:
An interviewer's private contemporaneous observation that becomes visible and immutable when the Interview ends.
_Avoid_: Score, formal review

**AI Analysis**:
An evidence-backed evaluation derived only from the interview recording and its transcript.
_Avoid_: Interview result, final decision

**Human Review**:
One assigned interviewer's editable post-interview assessment of the candidate.
_Avoid_: AI score, final result

**Final Decision**:
The HR/Admin-confirmed outcome recorded only after every assigned interviewer has submitted a Human Review.
_Avoid_: AI recommendation, average score

**AI Recommendation**:
A non-binding suggested outcome produced by AI from recording evidence.
_Avoid_: Final Decision

**Gate Dimension**:
A mandatory scoring dimension whose failure constrains the AI Recommendation regardless of weighted score.
_Avoid_: Knockout question
