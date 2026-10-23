---
name: meeting-minutes
description: Use to turn meeting notes or transcripts into the company's standard meeting minutes. Not for scheduling meetings or making meeting slides.
---
# Standard meeting minutes

Turns scattered meeting notes into the company's standard minutes.

## Format (this order, these headers)
```
Minutes | {meeting name} | {date}
Attendees: {names}

■ Decisions
- decision 1
■ Action Items
- {task} / {owner} / {due}
■ Next Meeting
- {date · time · agenda}
```

## Rules
- Decisions start with `Agreed to ...`. If something was discussed without a conclusion, it is not a decision
- Every action item needs an owner and a due date. If the notes don't say, write `owner TBD` or `due TBD` — never invent them
- Don't copy who said what
- If the notes have no next meeting, write `- TBD`
- No summary line or greeting before or after
