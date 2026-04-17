## ADDED Requirements

### Requirement: Ephemeral Conversation
The system SHALL maintain an in-memory conversation context per chat session for
discussion mode. The context consists of a rolling summary and a window of recent
messages bounded by discussion.max_history (config, default 20). When the message
window exceeds the limit, the oldest half of the messages SHALL be compacted into
the rolling summary using the discussion model.

#### Scenario: Multi-turn discussion
- **WHEN** the user is in discussion mode and sends follow-up messages
- **THEN** the system SHALL include the rolling summary and recent messages
  as context for the discussion model

#### Scenario: History compaction
- **WHEN** the recent message window exceeds discussion.max_history
- **THEN** the system SHALL compact the oldest half of the messages together
  with the existing rolling summary into a new summary using the discussion model
- **AND** remove the compacted messages from the recent window

#### Scenario: Rolling summary grows
- **WHEN** compaction runs multiple times during a long discussion
- **THEN** each compaction SHALL merge the previous summary with the newly
  overflowing messages into one updated summary

#### Scenario: Session cleared
- **WHEN** the user sends /clear and confirms
- **THEN** both the rolling summary and message history SHALL be discarded
  from memory and from SQLite

### Requirement: Discussion Entry
The system SHALL enter discussion mode either when the AI classifies a message
as a question or when the user sends /chat.

#### Scenario: AI-triggered discussion
- **WHEN** the categorization model classifies intent as a question
- **THEN** the system SHALL route the message to the discussion model with
  relevant project context

#### Scenario: Command-triggered discussion
- **WHEN** the user sends /chat
- **THEN** the system SHALL enter discussion mode and route subsequent messages
  to the discussion model

### Requirement: Discussion Exit
The system SHALL exit discussion mode when the user expresses intent to end the
conversation through natural language (e.g., "let's end this", "done", "exit").
The AI SHALL detect exit intent. If the discussion is idle for a configurable
duration (discussion.stale_minutes in config, default 30), the bot SHALL ask the
user whether to save or discard the conversation.

#### Scenario: Natural language exit
- **WHEN** the user expresses intent to end the discussion
- **THEN** the system SHALL ask whether to save the discussion to project notes
  or discard it

#### Scenario: Stale conversation prompt
- **WHEN** no messages are received for discussion.stale_minutes
- **THEN** a background asyncio task SHALL fire and send a Telegram message
  asking the user whether to save or discard the conversation context
- **AND** the timer SHALL reset on each incoming message

#### Scenario: Stale timer after restart
- **WHEN** the bot restarts while a discussion was active
- **THEN** the stale timer SHALL be re-initialized based on the current time
  (not the time of the last message before restart)

#### Scenario: User chooses to save on exit
- **WHEN** the user chooses to save during exit
- **THEN** the system SHALL trigger the dump-to-notes flow before exiting

#### Scenario: User chooses to discard on exit
- **WHEN** the user chooses to discard during exit
- **THEN** the system SHALL clear the conversation context (in-memory and SQLite)
  and return to normal capture mode

### Requirement: Dump to Notes
The system SHALL provide a /save command that summarizes the current discussion
using the discussion model and appends the summary to a project's notes.

#### Scenario: User saves discussion to project
- **WHEN** the user sends /save or chooses to save during exit
- **THEN** the system SHALL use the discussion model to summarize the
  conversation into concise notes
- **AND** ask the user to confirm or edit the target project
- **AND** append the summary to the project's notes
- **AND** trigger an Obsidian sync

#### Scenario: Save with no active discussion
- **WHEN** the user sends /save with no discussion history
- **THEN** the system SHALL inform the user there is nothing to save

### Requirement: Discussion State Persistence
The system SHALL persist discussion mode state (active flag, rolling summary,
and pending confirmations) to SQLite so they survive bot restarts. Recent
message history remains in-memory and is lost on restart.

#### Scenario: Bot restarts during discussion
- **WHEN** the bot restarts while a discussion was active
- **THEN** the system SHALL restore the discussion mode flag and rolling
  summary from SQLite
- **AND** inform the user that recent messages were lost but the conversation
  summary is preserved

#### Scenario: Pending confirmation survives restart
- **WHEN** the bot restarts while a project creation confirmation is pending
- **THEN** the system SHALL restore the pending confirmation from SQLite
