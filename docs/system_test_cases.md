# Task Buddy — Comprehensive System Test Cases

This document defines the system-level and integration-level test cases for the Task Buddy application. All test scenarios strictly conform to the QA specification guidelines: zero-padded scenario naming, 8-column design structure, and blank metadata columns on subsequent rows to denote visual nesting.

---

## 📋 System Test Cases (Design-Time Specification)

| TEST CASE NAME | POSITIVE/ NEGATIVE | TYPE | DESCRIPTION | PRE-CONDITION | TEST STEP NO. | TEST STEP DESCRIPTION | TEST EXPECTED RESULT |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `TC001_Sys_Pos_RegisterNewUser` | Positive | System | Validate registering a new user account with unique credentials. | User is on the registration page; no account exists with the target email. | Step 1 | Navigate to registration page (`/register`). | Registration page loads with email, username, password, confirm password fields, and submit button. |
| | | | | | Step 2 | Fill in a valid unique email, username, and password. | Input fields are populated correctly with no local validation errors. |
| | | | | | Step 3 | Click the "Sign Up" button. | Form is submitted. User is redirected to Dashboard (`/tasks`), and welcome/verification toast appears. |
| `TC002_Sys_Neg_RegisterDuplicateEmail` | Negative | System | Validate registration failure when using an already registered email. | User is on registration page; target email exists in the database. | Step 1 | Navigate to registration page (`/register`). | Registration page loads successfully. |
| | | | | | Step 2 | Input duplicate email, valid username, and matching passwords. | Form is filled out. No local validation errors appear. |
| | | | | | Step 3 | Click the "Sign Up" button. | Server rejects request. Error message "Email already registered" is shown below the email field. RED alert is displayed. |
| `TC003_Sys_Pos_UserLogin` | Positive | System | Validate standard login flow with correct registered credentials. | User is on the login page; user account is fully registered and active. | Step 1 | Navigate to login page (`/login`). | Login page loads with email and password fields, and "Sign In" button. |
| | | | | | Step 2 | Input valid registered email and correct matching password. | Input fields successfully populated. |
| | | | | | Step 3 | Click "Sign In" button. | User authenticated, redirected to main Tasks dashboard (`/tasks`), and sidebar loads user projects. |
| `TC004_Sys_Neg_LoginInvalidCredentials` | Negative | System | Validate authentication failure when logging in with incorrect password. | User is on the login page; account exists. | Step 1 | Navigate to login page (`/login`). | Login page loads successfully. |
| | | | | | Step 2 | Input registered email and an incorrect password. | Fields populated. |
| | | | | | Step 3 | Click "Sign In" button. | Authentication fails. Top banner shows "Invalid email or password". Fields retained, password field cleared. |
| `TC005_Sys_Pos_CreateNewProject` | Positive | System | Validate creating a new project container from the Sidebar. | User is logged in and viewing the main dashboard (`/tasks`). | Step 1 | Click the "+" action button next to "Projects" in the Sidebar. | "Create Project" Dialog/Modal opens with name input and color palette picker. |
| | | | | | Step 2 | Enter project name "Personal Tasks" and pick violet color theme. | Form is populated; violet circle highlights the selection. |
| | | | | | Step 3 | Click "Save" button in the modal. | Dialog closes. Project is saved and immediately appears in Sidebar list under "Projects" with violet indicator. |
| `TC006_Sys_Pos_DeleteProjectConfirmation` | Positive | System | Validate that deleting a project triggers the top-level confirmation modal. | Project "Personal Tasks" exists and is populated with tasks. | Step 1 | Click the vertical ellipsis action menu on "Personal Tasks" in the Sidebar. | Context menu appears showing "Edit" and "Delete" options. |
| | | | | | Step 2 | Click "Delete" action. | The top-level confirmation modal is triggered, warning that all tasks inside will be permanently deleted. |
| | | | | | Step 3 | Click "Confirm Delete" in the modal. | Project and all associated task cards are removed from UI. Top-right success toast appears. |
| `TC007_Sys_Pos_CreateNewTask` | Positive | System | Validate task creation and project binding. | Project "Personal Tasks" exists. | Step 1 | Click "Add Task" button at the header of the Tasks view. | "Add Task" modal opens with Title, Description, Priority, Due Date, Project, and Tags. |
| | | | | | Step 2 | Input Title "Refactor Confirmation Modals", choose High priority, tomorrow's date, and select "Personal Tasks" project. | Form populated with complete metadata. |
| | | | | | Step 3 | Click "Create" button. | Modal closes. New task card is rendered within the "Personal Tasks" container list with a "High" badge. |
| `TC008_Sys_Pos_AddSubtaskToTask` | Positive | System | Validate adding subtasks to an existing task in details drawer. | Task card "Refactor Confirmation Modals" exists. | Step 1 | Click the task card "Refactor Confirmation Modals". | Task Details Drawer slides open on the right side of the screen. |
| | | | | | Step 2 | Scroll to the "Subtasks" section and click "Add Subtask" input. | Subtask input becomes active with focused cursor. |
| | | | | | Step 3 | Enter "Remove inline DeleteConfirmView from ActionFooter" and press Enter. | Subtask is created, dynamically appended below task, and database is synced. |
| `TC009_Sys_Pos_DeleteSubtaskWithConfirmation` | Positive | System | Validate that deleting a subtask triggers the top-level confirmation modal. | Subtask "Remove inline DeleteConfirmView from ActionFooter" exists. | Step 1 | Open Task Details Drawer for "Refactor Confirmation Modals". | Drawer loads with subtasks. |
| | | | | | Step 2 | Hover over the target subtask and click the trash can delete icon. | Top-level confirmation modal is triggered, displaying a warning. |
| | | | | | Step 3 | Click "Confirm" button. | Subtask is removed from the list and database. Confirmation modal closes, and success toast displays. |
| `TC010_Sys_Pos_ToggleTaskCompletion` | Positive | System | Validate task completion toggling and state animation. | Task "Refactor Confirmation Modals" is incomplete. | Step 1 | Locate "Refactor Confirmation Modals" card on the Tasks page. | Task card is displayed in active list. |
| | | | | | Step 2 | Click the circular checkbox on the left of the task card. | Checkbox toggles to checked state. Database registers completed timestamp. |
| | | | | | Step 3 | Observe UI transition. | Task card description displays a line-through, and smoothly animates to the "Completed Tasks" group. |
| `TC011_Sys_Pos_FilterTasksByTagAndProject` | Positive | System | Validate memoized tag and project filtering. | Project "Personal Tasks" contains multiple tasks with "Refactor" tag. | Step 1 | Click "Personal Tasks" in the sidebar list. | Task page filters to show only tasks belonging to "Personal Tasks". |
| | | | | | Step 2 | Click the "Refactor" tag indicator in the filters menu. | Active filters include Project: "Personal Tasks" AND Tag: "Refactor". Filter results match immediately. |
| | | | | | Step 3 | Click the Sort select menu and select "Sort by Priority (High to Low)". | Task card list is rearranged instantly with high priority tasks at the top, driven by memoized selectors. |
| `TC012_API_Neg_EndpointRateLimitingTriggered` | Negative | API | Validate backend API rate limiting on project/task creation. | User has authenticated and obtained valid JWT auth token. | Step 1 | Obtain valid bearer token. | Bearer token verified in headers. |
| | | | | | Step 2 | Send 101 POST requests to `/api/v1/projects` within a 60-second window. | Requests processed sequentially in rapid loop. |
| | | | | | Step 3 | Inspect the response code of the 101st request. | Response returns status code `429 Too Many Requests` with a rate-limit payload wrapper. |
| `TC013_Sys_Neg_CreateTaskEmptyTitle` | Negative | System | Validate that task creation fails when the title is empty. | User is on the tasks page; "Add Task" modal is open. | Step 1 | Leave the "Title" input field completely blank. Fill out valid Description, Due Date, and select a valid Project. | Form contains valid inputs except for the empty Title. |
| | | | | | Step 2 | Click the "Create" button. | Form submission is blocked. A clear validation error "Title is required" is displayed in RED below the title field. |
| `TC014_Sys_Pos_CreateTaskMinTitle` | Positive | System | Validate task creation with a title of exactly 1 character (lower bound). | "Add Task" modal is open. | Step 1 | Enter a single character "A" in the Task Title field. | Title input displays "A". |
| | | | | | Step 2 | Click the "Create" button. | Task is successfully created, the modal closes, and the task card showing title "A" appears in the active task list. |
| `TC015_Sys_Pos_CreateTaskMaxTitle` | Positive | System | Validate task creation with a title of exactly 100 characters (upper bound). | "Add Task" modal is open. | Step 1 | Enter a title string of exactly 100 characters in the Title field. | The character count indicator shows "100/100" and no overflow error is shown. |
| | | | | | Step 2 | Click the "Create" button. | Task is created successfully, the modal closes, and the complete 100-character title is rendered on the task card. |
| `TC016_Sys_Neg_CreateTaskExceedMaxTitle` | Negative | System | Validate that entering a title of 101 characters triggers an immediate boundary error. | "Add Task" modal is open. | Step 1 | Attempt to input a 101-character string into the Title field. | Input blocks extra character, or the character counter turns red displaying "101/100" and the submit button is disabled. |
| | | | | | Step 2 | Click the "Create" button. | Submission is blocked. Validation message "Title must be 100 characters or less" appears below the input. |
| `TC017_Sys_Pos_CreateTaskEmptyDescription` | Positive | System | Validate task creation with an empty description (optional field). | "Add Task" modal is open. | Step 1 | Input a valid Title, but leave the Description text area completely empty. | Description input field remains blank. |
| | | | | | Step 2 | Click the "Create" button. | Task is created successfully. In task details drawer, the description field displays "No description provided." |
| `TC018_Sys_Pos_CreateTaskMaxDescription` | Positive | System | Validate task creation with a description of exactly 2000 characters (upper bound). | "Add Task" modal is open. | Step 1 | Enter a valid Title and paste a description block containing exactly 2000 characters. | Text is fully inserted. Character counter displays "2000/2000". |
| | | | | | Step 2 | Click the "Create" button. | Task is created. Opening the task details drawer shows the full 2000-character description without any truncation. |
| `TC019_Sys_Neg_CreateTaskExceedMaxDescription` | Negative | System | Validate validation handling when description exceeds 2000 characters. | "Add Task" modal is open. | Step 1 | Attempt to paste a description block containing 2001 characters. | Paste is truncated at 2000 characters, or character counter turns red and shows "2001/2000". |
| | | | | | Step 2 | Click the "Create" button. | Submit button remains disabled, or form blocks submission with message "Description cannot exceed 2000 characters". |
| `TC020_Sys_Neg_CreateTaskPastDueDate` | Negative | System | Validate that setting the task due date in the past is rejected. | "Add Task" modal is open. | Step 1 | Click the Date Picker and select yesterday's calendar date. | The selected date is set to a past date. |
| | | | | | Step 2 | Enter a valid Title and click the "Create" button. | Submit action is blocked. Error tooltip displays "Due date cannot be in the past". |
| `TC021_Sys_Pos_CreateTaskTodayDueDate` | Positive | System | Validate task creation with a due date set to today (lower bound). | "Add Task" modal is open. | Step 1 | Click the Date Picker and select today's calendar date. | Today's date is set in the date field. |
| | | | | | Step 2 | Enter a valid Title and click the "Create" button. | Task is successfully created. Task card renders with a due date badge labeled "Today" in amber. |
| `TC022_Sys_Pos_CreateTaskFarFutureDueDate` | Positive | System | Validate task creation with a due date set to a far future date (upper bound). | "Add Task" modal is open. | Step 1 | Click the Date Picker and select "2099-12-31" in the calendar view. | The date field displays "2099-12-31". |
| | | | | | Step 2 | Enter a valid Title and click the "Create" button. | Task is successfully created. Task card renders with a due date badge showing "Dec 31, 2099". |
| `TC023_Sys_Neg_CreateTaskInvalidDateFormat` | Negative | API | Validate that the backend API rejects tasks with malformed due date values. | User is authenticated with a valid bearer token; using an API client. | Step 1 | Send a POST request to `/api/v1/tasks` with due_date set to "invalid-date-string". | Request payload is processed by server schema validator. |
| | | | | | Step 2 | Inspect the response status code and payload structure. | Response returns status code `400 Bad Request` with error: "due_date must be in YYYY-MM-DD format". |
| `TC024_Sys_Pos_CreateTaskMidnightTime` | Positive | System | Validate task creation with due time set to exactly 00:00 (midnight lower bound). | "Add Task" modal is open. | Step 1 | Click the Time Picker and set hour to "00" and minutes to "00". | The time field displays "00:00" (or 12:00 AM). |
| | | | | | Step 2 | Enter a valid Title and click the "Create" button. | Task is created. Drawer shows "Due Time: 12:00 AM". |
| `TC025_Sys_Pos_CreateTaskEndDayTime` | Positive | System | Validate task creation with due time set to exactly 23:59 (end of day upper bound). | "Add Task" modal is open. | Step 1 | Click the Time Picker and set hour to "23" and minutes to "59". | The time field displays "23:59" (or 11:59 PM). |
| | | | | | Step 2 | Enter a valid Title and click the "Create" button. | Task is created. Drawer shows "Due Time: 11:59 PM". |
| `TC026_Sys_Neg_CreateTaskInvalidTimeFormat` | Negative | API | Validate that the backend API rejects invalid time structures. | User is authenticated with a valid bearer token; using an API client. | Step 1 | Send a POST request to `/api/v1/tasks` with due_time set to "24:00" or "12:60". | Server parses and validates payload attributes. |
| | | | | | Step 2 | Inspect the response status code and message. | Response returns status code `400 Bad Request` with error: "due_time must be a valid time format". |
| `TC027_Sys_Pos_CreateTaskWithZeroSubtasks` | Positive | System | Validate task creation with zero subtasks (lower bound). | "Add Task" modal is open. | Step 1 | Enter a valid Title and leave the subtasks list container completely empty. | No subtasks are listed in the modal view. |
| | | | | | Step 2 | Click the "Create" button. | Task is successfully created. Details drawer shows "0 Subtasks" and progress indicator is hidden. |
| `TC028_Sys_Pos_CreateTaskWithOneSubtask` | Positive | System | Validate task creation with exactly one subtask (lower bound step). | "Add Task" modal is open. | Step 1 | Enter a valid Title, then type "Subtask Item 1" in the subtask field and press Enter. | One subtask item is rendered with an active delete icon next to it. |
| | | | | | Step 2 | Click the "Create" button. | Task is created. Details drawer lists exactly one subtask and subtask progress bar shows "0% (0/1)". |
| `TC029_Sys_Pos_CreateTaskWithMaxSubtasks` | Positive | System | Validate task creation containing exactly 50 subtasks (upper bound). | "Add Task" modal is open. | Step 1 | Enter a valid Title, then add exactly 50 subtask items using the "Add" field. | Form renders 50 subtasks. The "Add" input becomes disabled, showing tooltip "Subtask limit (50) reached". |
| | | | | | Step 2 | Click the "Create" button. | Task is created successfully with all 50 subtasks synchronized to the database. |
| `TC030_Sys_Neg_CreateTaskExceedMaxSubtasks` | Negative | System | Validate that adding a 51st subtask is blocked by the UI and API. | A task card exists containing exactly 50 subtasks; details drawer is open. | Step 1 | Locate the subtask input bar. | The subtask input bar is greyed out/disabled, preventing text entry. |
| | | | | | Step 2 | Attempt to send POST request adding a 51st subtask via API client. | API returns `400 Bad Request` with error message "Cannot exceed 50 subtasks per task". |
| `TC031_Sys_Neg_AddSubtaskEmptyTitle` | Negative | System | Validate that adding a subtask with an empty title is rejected. | Task details drawer is open. | Step 1 | Click "Add Subtask" input field and press Enter without entering any characters. | Input field is focused but no list item is created. |
| | | | | | Step 2 | Inspect the input validation state. | A temporary red warning border or tooltip appears showing "Subtask title cannot be empty". |
| `TC032_Sys_Pos_AddSubtaskMinTitle` | Positive | System | Validate adding a subtask with exactly 1 character (lower bound). | Task details drawer is open. | Step 1 | Type a single character "X" into the subtask input and press Enter. | Subtask "X" is successfully created in the database and loaded in list. |
| | | | | | Step 2 | Verify drawer presentation. | The subtask is rendered with description "X" and an unchecked checkbox. |
| `TC033_Sys_Pos_AddSubtaskMaxTitle` | Positive | System | Validate adding a subtask with a title of exactly 80 characters (upper bound). | Task details drawer is open. | Step 1 | Input an 80-character title (e.g., "Refactor subtasks layout using flex containers and absolute positioned action icons") in the subtask field and press Enter. | Subtask is created successfully and fits neatly in the drawer bounds. |
| | | | | | Step 2 | Verify database persistence. | The subtask title is stored and loaded as exactly 80 characters with no trailing truncations. |
| `TC034_Sys_Neg_AddSubtaskExceedMaxTitle` | Negative | System | Validate that adding a subtask with 81 characters is restricted. | Task details drawer is open. | Step 1 | Attempt to type a 81-character title into the subtask input field. | Input box prevents typing past 80 characters, or displays warning indicator "81/80". |
| | | | | | Step 2 | Press Enter. | The form restricts submission or truncates the input string to exactly 80 characters. |
| `TC035_Sys_Pos_CreateTaskWithZeroTags` | Positive | System | Validate creating a task without attaching any tags (lower bound). | "Add Task" modal is open. | Step 1 | Fill out a valid Title and leave the tags input field empty. | No tag badges are displayed in the form. |
| | | | | | Step 2 | Click the "Create" button. | Task is created successfully. Task card renders with no tag container. |
| `TC036_Sys_Pos_CreateTaskWithMaxTags` | Positive | System | Validate task creation with exactly 10 tags (upper bound). | "Add Task" modal is open. | Step 1 | Enter exactly 10 unique tags sequentially in the tags field. | 10 tag badges are displayed. The tags text input is disabled/hidden. |
| | | | | | Step 2 | Click the "Create" button. | Task is created successfully. Task card renders all 10 badges within the card tag row. |
| `TC037_Sys_Neg_CreateTaskExceedMaxTags` | Negative | System | Validate that adding an 11th tag is blocked. | "Add Task" modal is open; 10 tags are active. | Step 1 | Attempt to type an 11th tag value. | Tag input box remains disabled with tooltip: "Tag limit (10) reached". |
| | | | | | Step 2 | Submit a task creation API request containing 11 tags. | API server rejects request, returning `400 Bad Request` with error "Cannot exceed 10 tags per task". |
| `TC038_Sys_Pos_CreateTaskMinTagLength` | Positive | System | Validate creating a tag containing exactly 1 character (lower bound). | "Add Task" modal is open. | Step 1 | Type "Q" in the tag input field and press Enter. | A tag badge displaying "Q" is added to the form. |
| | | | | | Step 2 | Click the "Create" button. | Task is saved. Task card shows badge "Q" in the tag list. |
| `TC039_Sys_Pos_CreateTaskMaxTagLength` | Positive | System | Validate creating a tag containing exactly 20 characters (upper bound). | "Add Task" modal is open. | Step 1 | Type "BackendOptimizationQ" (exactly 20 characters) and press Enter. | A tag badge displaying "BackendOptimizationQ" is added successfully. |
| | | | | | Step 2 | Click the "Create" button. | Task is saved. The tag card shows the complete 20-character tag. |
| `TC040_Sys_Neg_CreateTaskExceedMaxTagLength` | Negative | System | Validate that entering a tag title > 20 characters is blocked. | "Add Task" modal is open. | Step 1 | Attempt to input "BackendOptimizationQ!" (21 characters) in the tag input. | Input blocks input past 20 characters, or displays warning error "Tag length cannot exceed 20 characters". |
| | | | | | Step 2 | Press Enter. | Form blocks tag creation or automatically truncates the tag to 20 characters. |
| `TC041_Sys_Pos_CreateTaskUnicodeEmojis` | Positive | System | Validate task creation with unicode and emoji symbols in task title. | "Add Task" modal is open. | Step 1 | Type "🚀 Deploy v1.4 codebase 🛡️" as the task title. | Title input displays emojis and unicode symbols correctly. |
| | | | | | Step 2 | Click the "Create" button. | Task is successfully saved. Emojis render correctly on the dashboard task card and task details drawer. |
| `TC042_Sys_Pos_CreateTaskXSSSanitization` | Positive | System | Validate that XSS script payloads in task descriptions are sanitized. | "Add Task" modal is open. | Step 1 | Enter a valid Title and paste `<script>alert('XSS')</script><img src="x" onerror="alert(1)">` into the description. | Text is accepted literally in the text area. |
| | | | | | Step 2 | Click "Create", and click the new task card to open the Details drawer. | Drawer renders description safely as literal text string; no script runs, showing solid sanitization. |
| `TC043_Sys_Pos_CreateTaskSQLInjectionPrevention` | Positive | System | Validate that SQL injection payloads are treated as literal text values. | "Add Task" modal is open. | Step 1 | Enter `' OR 1=1; DROP TABLE tbl_tasks; --` in the task Title input field. | String is entered literally. |
| | | | | | Step 2 | Click "Create" button. | Task is created successfully with the injection payload as its literal title. Database integrity is preserved. |
| `TC044_Sys_Neg_CreateTaskNonexistentProject` | Negative | API | Validate that task creation fails when selecting a nonexistent project ID. | User has authenticated and obtained valid bearer token; using API client. | Step 1 | Send a POST request to `/api/v1/tasks` with project_id set to "999999" (nonexistent). | API checks project association. |
| | | | | | Step 2 | Inspect response status code and body. | Server returns `400 Bad Request` or `404 Not Found` with message: "Project not found". |
| `TC045_Sys_Pos_CreateTaskDefaultPriority` | Positive | System | Validate that task creation defaults to "Medium" priority when none is specified. | "Add Task" modal is open. | Step 1 | Enter a valid Title, but leave the priority selector default. | Priority selector field displays no high/low overrides. |
| | | | | | Step 2 | Click "Create" button. | Task is created. Dashboard task card displays a grey "Medium" priority badge by default. |

---

## 🛠️ QA Verification Checklist

Review all added test cases using this quality control gate before executing:

- [ ] **Naming Schema**: Matches `TC[Number]_[Type]_[Pos/Neg]_[ActionCamelCase]`.
- [ ] **Column Count**: Exactly 8 columns utilized for design.
- [ ] **Step Nesting**: Rows 2+ of the same test case have empty columns for Columns 1 to 5 (`TEST CASE NAME` through `PRE-CONDITION`).
- [ ] **Step Format**: Every step number is formatted exactly as `Step N`.
- [ ] **Expected Results**: Written in verifiable terms (e.g., "Toast appears", "Redirected to...", "RED alert is shown").
