## ADDED Requirements

### Requirement: OpenAI-Compatible Client
The system SHALL communicate with AI models through an OpenAI-compatible API
interface using the openai Python package. The base URL, API key, and model name
SHALL be configurable per tier via the TOML config file (ai.categorization and
ai.discussion sections). Environment variables with the SECONDBRAIN_ prefix
SHALL override config file values.

#### Scenario: Categorization model call
- **WHEN** the system needs to categorize a message
- **THEN** it SHALL use the categorization tier configuration
  (ai.categorization.base_url, ai.categorization.api_key, ai.categorization.model)

#### Scenario: Discussion model call
- **WHEN** the system needs to respond in discussion mode
- **THEN** it SHALL use the discussion tier configuration
  (ai.discussion.base_url, ai.discussion.api_key, ai.discussion.model)

#### Scenario: Provider flexibility
- **WHEN** the system is configured with any OpenAI-compatible endpoint
- **THEN** it SHALL work with Ollama, OpenAI, Anthropic (via proxy), or any
  other compatible provider without code changes

### Requirement: AI Request Timeout
The system SHALL enforce a configurable timeout on all AI API calls
(ai.timeout_seconds in config, default 30). On timeout, the system SHALL inform
the user and not upsert any data.

#### Scenario: AI call times out
- **WHEN** an AI API call exceeds the configured timeout
- **THEN** the system SHALL cancel the request
- **AND** reply to the user indicating the AI is temporarily unavailable

#### Scenario: AI call succeeds within timeout
- **WHEN** an AI API call completes within the timeout
- **THEN** the system SHALL process the response normally

### Requirement: Defensive Response Parsing
The system SHALL parse AI responses defensively using a three-tier fallback:
first attempt JSON parse of the full response, then extract the first {...}
block from the text, and finally fall back to treating the response as a plain
message with no data upsert.

#### Scenario: Clean JSON response
- **WHEN** the AI returns a response that is valid JSON
- **THEN** the system SHALL parse and use the structured data

#### Scenario: JSON embedded in text
- **WHEN** the AI returns text containing a JSON object
- **THEN** the system SHALL extract the first {...} block and parse it

#### Scenario: No parseable JSON
- **WHEN** the AI returns text with no valid JSON
- **THEN** the system SHALL treat it as a plain conversational reply
- **AND** SHALL NOT upsert any project data

### Requirement: Categorization Prompt
The system SHALL send the categorization model a prompt that includes the user
message, the list of existing project names (including aliases), and instructions
to classify intent (note vs question) and extract structured project data as JSON.
The prompt SHALL instruct the model to omit fields it cannot infer rather than
returning null values.

#### Scenario: Message with known project context
- **WHEN** the user sends a message about an existing project
- **THEN** the prompt SHALL include existing project names and aliases so the
  model can match against them

#### Scenario: Categorization JSON schema
- **WHEN** the categorization model responds
- **THEN** the expected JSON SHALL include: intent (note/question), project_id,
  project_name, description, stack, tags, status, and notes fields
- **AND** omitted fields SHALL mean "no change" during upsert

#### Scenario: Field update semantics
- **WHEN** the AI response includes a field with a value
- **THEN** the system SHALL update that field on the project
- **WHEN** the AI response omits a field entirely
- **THEN** the system SHALL leave the existing value unchanged
