import os

testcases = [
    {
        "name": "TC001_Sys_Pos_RegisterNewUser",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate registering a new user account with unique credentials.",
        "pre": "User is on the registration page; no account exists with the target email.",
        "steps": [
            ("Step 1", "Navigate to registration page (`/register`).", "Registration page loads with email, username, password, confirm password fields, and submit button."),
            ("Step 2", "Fill in a valid unique email, username, and password.", "Input fields are populated correctly with no local validation errors."),
            ("Step 3", "Click the \"Sign Up\" button.", "Form is submitted. User is redirected to Dashboard (`/tasks`), and welcome/verification toast appears.")
        ]
    },
    {
        "name": "TC002_Sys_Neg_RegisterDuplicateEmail",
        "pos_neg": "Negative",
        "type": "System",
        "desc": "Validate registration failure when using an already registered email.",
        "pre": "User is on registration page; target email exists in the database.",
        "steps": [
            ("Step 1", "Navigate to registration page (`/register`).", "Registration page loads successfully."),
            ("Step 2", "Input duplicate email, valid username, and matching passwords.", "Form is filled out. No local validation errors appear."),
            ("Step 3", "Click the \"Sign Up\" button.", "Server rejects request. Error message \"Email already registered\" is shown below the email field. RED alert is displayed.")
        ]
    },
    {
        "name": "TC003_Sys_Pos_UserLogin",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate standard login flow with correct registered credentials.",
        "pre": "User is on the login page; user account is fully registered and active.",
        "steps": [
            ("Step 1", "Navigate to login page (`/login`).", "Login page loads with email and password fields, and \"Sign In\" button."),
            ("Step 2", "Input valid registered email and correct matching password.", "Input fields successfully populated."),
            ("Step 3", "Click \"Sign In\" button.", "User authenticated, redirected to main Tasks dashboard (`/tasks`), and sidebar loads user projects.")
        ]
    },
    {
        "name": "TC004_Sys_Neg_LoginInvalidCredentials",
        "pos_neg": "Negative",
        "type": "System",
        "desc": "Validate authentication failure when logging in with incorrect password.",
        "pre": "User is on the login page; account exists.",
        "steps": [
            ("Step 1", "Navigate to login page (`/login`).", "Login page loads successfully."),
            ("Step 2", "Input registered email and an incorrect password.", "Fields populated."),
            ("Step 3", "Click \"Sign In\" button.", "Authentication fails. Top banner shows \"Invalid email or password\". Fields retained, password field cleared.")
        ]
    },
    {
        "name": "TC005_Sys_Pos_CreateNewProject",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate creating a new project container from the Sidebar.",
        "pre": "User is logged in and viewing the main dashboard (`/tasks`).",
        "steps": [
            ("Step 1", "Click the \"+\" action button next to \"Projects\" in the Sidebar.", "\"Create Project\" Dialog/Modal opens with name input and color palette picker."),
            ("Step 2", "Enter project name \"Personal Tasks\" and pick violet color theme.", "Form is populated; violet circle highlights the selection."),
            ("Step 3", "Click \"Save\" button in the modal.", "Dialog closes. Project is saved and immediately appears in Sidebar list under \"Projects\" with violet indicator.")
        ]
    },
    {
        "name": "TC006_Sys_Pos_DeleteProjectConfirmation",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate that deleting a project triggers the top-level confirmation modal.",
        "pre": "Project \"Personal Tasks\" exists and is populated with tasks.",
        "steps": [
            ("Step 1", "Click the vertical ellipsis action menu on \"Personal Tasks\" in the Sidebar.", "Context menu appears showing \"Edit\" and \"Delete\" options."),
            ("Step 2", "Click \"Delete\" action.", "The top-level confirmation modal is triggered, warning that all tasks inside will be permanently deleted."),
            ("Step 3", "Click \"Confirm Delete\" in the modal.", "Project and all associated task cards are removed from UI. Top-right success toast appears.")
        ]
    },
    {
        "name": "TC007_Sys_Pos_CreateNewTask",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate task creation and project binding.",
        "pre": "Project \"Personal Tasks\" exists.",
        "steps": [
            ("Step 1", "Click \"Add Task\" button at the header of the Tasks view.", "\"Add Task\" modal opens with Title, Description, Priority, Due Date, Project, and Tags."),
            ("Step 2", "Input Title \"Refactor Confirmation Modals\", choose High priority, tomorrow's date, and select \"Personal Tasks\" project.", "Form populated with complete metadata."),
            ("Step 3", "Click \"Create\" button.", "Modal closes. New task card is rendered within the \"Personal Tasks\" container list with a \"High\" badge.")
        ]
    },
    {
        "name": "TC008_Sys_Pos_AddSubtaskToTask",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate adding subtasks to an existing task in details drawer.",
        "pre": "Task card \"Refactor Confirmation Modals\" exists.",
        "steps": [
            ("Step 1", "Click the task card \"Refactor Confirmation Modals\".", "Task Details Drawer slides open on the right side of the screen."),
            ("Step 2", "Scroll to the \"Subtasks\" section and click \"Add Subtask\" input.", "Subtask input becomes active with focused cursor."),
            ("Step 3", "Enter \"Remove inline DeleteConfirmView from ActionFooter\" and press Enter.", "Subtask is created, dynamically appended below task, and database is synced.")
        ]
    },
    {
        "name": "TC009_Sys_Pos_DeleteSubtaskWithConfirmation",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate that deleting a subtask triggers the top-level confirmation modal.",
        "pre": "Subtask \"Remove inline DeleteConfirmView from ActionFooter\" exists.",
        "steps": [
            ("Step 1", "Open Task Details Drawer for \"Refactor Confirmation Modals\".", "Drawer loads with subtasks."),
            ("Step 2", "Hover over the target subtask and click the trash can delete icon.", "Top-level confirmation modal is triggered, displaying a warning."),
            ("Step 3", "Click \"Confirm\" button.", "Subtask is removed from the list and database. Confirmation modal closes, and success toast displays.")
        ]
    },
    {
        "name": "TC010_Sys_Pos_ToggleTaskCompletion",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate task completion toggling and state animation.",
        "pre": "Task \"Refactor Confirmation Modals\" is incomplete.",
        "steps": [
            ("Step 1", "Locate \"Refactor Confirmation Modals\" card on the Tasks page.", "Task card is displayed in active list."),
            ("Step 2", "Click the circular checkbox on the left of the task card.", "Checkbox toggles to checked state. Database registers completed timestamp."),
            ("Step 3", "Observe UI transition.", "Task card description displays a line-through, and smoothly animates to the \"Completed Tasks\" group.")
        ]
    },
    {
        "name": "TC011_Sys_Pos_FilterTasksByTagAndProject",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate memoized tag and project filtering.",
        "pre": "Project \"Personal Tasks\" contains multiple tasks with \"Refactor\" tag.",
        "steps": [
            ("Step 1", "Click \"Personal Tasks\" in the sidebar list.", "Task page filters to show only tasks belonging to \"Personal Tasks\"."),
            ("Step 2", "Click the \"Refactor\" tag indicator in the filters menu.", "Active filters include Project: \"Personal Tasks\" AND Tag: \"Refactor\". Filter results match immediately."),
            ("Step 3", "Click the Sort select menu and select \"Sort by Priority (High to Low)\".", "Task card list is rearranged instantly with high priority tasks at the top, driven by memoized selectors.")
        ]
    },
    {
        "name": "TC012_API_Neg_EndpointRateLimitingTriggered",
        "pos_neg": "Negative",
        "type": "API",
        "desc": "Validate backend API rate limiting on project/task creation.",
        "pre": "User has authenticated and obtained valid JWT auth token.",
        "steps": [
            ("Step 1", "Obtain valid bearer token.", "Bearer token verified in headers."),
            ("Step 2", "Send 101 POST requests to `/api/v1/projects` within a 60-second window.", "Requests processed sequentially in rapid loop."),
            ("Step 3", "Inspect the response code of the 101st request.", "Response returns status code `429 Too Many Requests` with a rate-limit payload wrapper.")
        ]
    },
    {
        "name": "TC013_Sys_Neg_CreateTaskEmptyTitle",
        "pos_neg": "Negative",
        "type": "System",
        "desc": "Validate that task creation fails when the title is empty.",
        "pre": "User is on the tasks page; \"Add Task\" modal is open.",
        "steps": [
            ("Step 1", "Leave the \"Title\" input field completely blank. Fill out valid Description, Due Date, and select a valid Project.", "Form contains valid inputs except for the empty Title."),
            ("Step 2", "Click the \"Create\" button.", "Form submission is blocked. A clear validation error \"Title is required\" is displayed in RED below the title field.")
        ]
    },
    {
        "name": "TC014_Sys_Pos_CreateTaskMinTitle",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate task creation with a title of exactly 1 character (lower bound).",
        "pre": "\"Add Task\" modal is open.",
        "steps": [
            ("Step 1", "Enter a single character \"A\" in the Task Title field.", "Title input displays \"A\"."),
            ("Step 2", "Click the \"Create\" button.", "Task is successfully created, the modal closes, and the task card showing title \"A\" appears in the active task list.")
        ]
    },
    {
        "name": "TC015_Sys_Pos_CreateTaskMaxTitle",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate task creation with a title of exactly 255 characters (upper bound).",
        "pre": "\"Add Task\" modal is open.",
        "steps": [
            ("Step 1", "Enter a title string of exactly 255 characters in the Title field.", "The character count indicator shows \"255/255\" and no overflow error is shown."),
            ("Step 2", "Click the \"Create\" button.", "Task is created successfully, the modal closes, and the complete 255-character title is rendered on the task card.")
        ]
    },
    {
        "name": "TC016_Sys_Neg_CreateTaskExceedMaxTitle",
        "pos_neg": "Negative",
        "type": "System",
        "desc": "Validate that entering a title of 256 characters triggers an immediate boundary error.",
        "pre": "\"Add Task\" modal is open.",
        "steps": [
            ("Step 1", "Attempt to input a 256-character string into the Title field.", "Input blocks extra character, or the character counter turns red displaying \"256/255\" and the submit button is disabled."),
            ("Step 2", "Click the \"Create\" button.", "Submission is blocked. Validation message \"Title must be 255 characters or less\" appears below the input.")
        ]
    },
    {
        "name": "TC017_Sys_Pos_CreateTaskEmptyDescription",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate task creation with an empty description (optional field).",
        "pre": "\"Add Task\" modal is open.",
        "steps": [
            ("Step 1", "Input a valid Title, but leave the Description text area completely empty.", "Description input field remains blank."),
            ("Step 2", "Click the \"Create\" button.", "Task is created successfully. In task details drawer, the description field displays \"No description provided.\"")
        ]
    },
    {
        "name": "TC018_Sys_Pos_CreateTaskMaxDescription",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate task creation with a description of exactly 2000 characters (upper bound).",
        "pre": "\"Add Task\" modal is open.",
        "steps": [
            ("Step 1", "Enter a valid Title and paste a description block containing exactly 2000 characters.", "Text is fully inserted. Character counter displays \"2000/2000\"."),
            ("Step 2", "Click the \"Create\" button.", "Task is created. Opening the task details drawer shows the full 2000-character description without any truncation.")
        ]
    },
    {
        "name": "TC019_Sys_Neg_CreateTaskExceedMaxDescription",
        "pos_neg": "Negative",
        "type": "System",
        "desc": "Validate validation handling when description exceeds 2000 characters.",
        "pre": "\"Add Task\" modal is open.",
        "steps": [
            ("Step 1", "Attempt to paste a description block containing 2001 characters.", "Paste is truncated at 2000 characters, or character counter turns red and shows \"2001/2000\"."),
            ("Step 2", "Click the \"Create\" button.", "Submit button remains disabled, or form blocks submission with message \"Description cannot exceed 2000 characters\".")
        ]
    },
    {
        "name": "TC020_Sys_Pos_CreateTaskPastDueDate",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate that setting the task due date in the past is successfully accepted by the system.",
        "pre": "\"Add Task\" modal is open.",
        "steps": [
            ("Step 1", "Click the Date Picker and select yesterday's calendar date.", "Yesterday's date is set."),
            ("Step 2", "Enter a valid Title and click the \"Create\" button.", "Task is successfully created."),
            ("Step 3", "Observe dashboard card.", "Task card renders with yesterday's due date in red/warning style.")
        ]
    },
    {
        "name": "TC021_Sys_Pos_CreateTaskTodayDueDate",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate task creation with a due date set to today (lower bound).",
        "pre": "\"Add Task\" modal is open.",
        "steps": [
            ("Step 1", "Click the Date Picker and select today's calendar date.", "Today's date is set in the date field."),
            ("Step 2", "Enter a valid Title and click the \"Create\" button.", "Task is successfully created. Task card renders with a due date badge labeled \"Today\" in amber.")
        ]
    },
    {
        "name": "TC022_Sys_Pos_CreateTaskFarFutureDueDate",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate task creation with a due date set to a far future date (upper bound).",
        "pre": "\"Add Task\" modal is open.",
        "steps": [
            ("Step 1", "Click the Date Picker and select \"2099-12-31\" in the calendar view.", "The date field displays \"2099-12-31\"."),
            ("Step 2", "Enter a valid Title and click the \"Create\" button.", "Task is successfully created. Task card renders with a due date badge showing \"Dec 31, 2099\".")
        ]
    },
    {
        "name": "TC023_Sys_Neg_CreateTaskInvalidDateFormat",
        "pos_neg": "Negative",
        "type": "API",
        "desc": "Validate that the backend API rejects tasks with malformed due date values.",
        "pre": "User is authenticated with a valid bearer token; using an API client.",
        "steps": [
            ("Step 1", "Send a POST request to `/api/v1/tasks` with due_date set to \"invalid-date-string\".", "Request payload is processed by server schema validator."),
            ("Step 2", "Inspect the response status code and payload structure.", "Response returns status code `400 Bad Request` with error: \"due_date must be in YYYY-MM-DD format\".")
        ]
    },
    {
        "name": "TC024_Sys_Pos_CreateTaskMidnightTime",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate task creation with due time set to exactly 00:00 (midnight lower bound).",
        "pre": "\"Add Task\" modal is open.",
        "steps": [
            ("Step 1", "Click the Time Picker and set hour to \"00\" and minutes to \"00\".", "The time field displays \"00:00\" (or 12:00 AM)."),
            ("Step 2", "Enter a valid Title and click the \"Create\" button.", "Task is created. Drawer shows \"Due Time: 12:00 AM\".")
        ]
    },
    {
        "name": "TC025_Sys_Pos_CreateTaskEndDayTime",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate task creation with due time set to exactly 23:59 (end of day upper bound).",
        "pre": "\"Add Task\" modal is open.",
        "steps": [
            ("Step 1", "Click the Time Picker and set hour to \"23\" and minutes to \"59\".", "The time field displays \"23:59\" (or 11:59 PM)."),
            ("Step 2", "Enter a valid Title and click the \"Create\" button.", "Task is created. Drawer shows \"Due Time: 11:59 PM\".")
        ]
    },
    {
        "name": "TC026_Sys_Neg_CreateTaskInvalidTimeFormat",
        "pos_neg": "Negative",
        "type": "API",
        "desc": "Validate that the backend API rejects invalid time structures.",
        "pre": "User is authenticated with a valid bearer token; using an API client.",
        "steps": [
            ("Step 1", "Send a POST request to `/api/v1/tasks` with due_time set to \"24:00\" or \"12:60\".", "Server parses and validates payload attributes."),
            ("Step 2", "Inspect the response status code and message.", "Response returns status code `400 Bad Request` with error: \"due_time must be a valid time format\".")
        ]
    },
    {
        "name": "TC027_Sys_Pos_CreateTaskWithZeroSubtasks",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate task creation with zero subtasks (lower bound).",
        "pre": "\"Add Task\" modal is open.",
        "steps": [
            ("Step 1", "Enter a valid Title and leave the subtasks list container completely empty.", "No subtasks are listed in the modal view."),
            ("Step 2", "Click the \"Create\" button.", "Task is successfully created. Details drawer shows \"0 Subtasks\" and progress indicator is hidden.")
        ]
    },
    {
        "name": "TC028_Sys_Pos_CreateTaskWithOneSubtask",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate task creation with exactly one subtask (lower bound step).",
        "pre": "\"Add Task\" modal is open.",
        "steps": [
            ("Step 1", "Enter a valid Title, then type \"Subtask Item 1\" in the subtask field and press Enter.", "One subtask item is rendered with an active delete icon next to it."),
            ("Step 2", "Click the \"Create\" button.", "Task is created. Details drawer lists exactly one subtask and subtask progress bar shows \"0% (0/1)\".")
        ]
    },
    {
        "name": "TC029_Sys_Pos_CreateTaskWithMaxSubtasks",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate task creation containing exactly 50 subtasks (upper bound).",
        "pre": "\"Add Task\" modal is open.",
        "steps": [
            ("Step 1", "Enter a valid Title, then add exactly 50 subtask items using the \"Add\" field.", "Form renders 50 subtasks. The \"Add\" input becomes disabled, showing tooltip \"Subtask limit (50) reached\"."),
            ("Step 2", "Click the \"Create\" button.", "Task is created successfully with all 50 subtasks synchronized to the database.")
        ]
    },
    {
        "name": "TC030_Sys_Neg_CreateTaskExceedMaxSubtasks",
        "pos_neg": "Negative",
        "type": "System",
        "desc": "Validate that adding a 51st subtask is blocked by the UI and API.",
        "pre": "A task card exists containing exactly 50 subtasks; details drawer is open.",
        "steps": [
            ("Step 1", "Locate the subtask input bar.", "The subtask input bar is greyed out/disabled, preventing text entry."),
            ("Step 2", "Attempt to send POST request adding a 51st subtask via API client.", "API returns `400 Bad Request` with error message \"Cannot exceed 50 subtasks per task\".")
        ]
    },
    {
        "name": "TC031_Sys_Neg_AddSubtaskEmptyTitle",
        "pos_neg": "Negative",
        "type": "System",
        "desc": "Validate that adding a subtask with an empty title is rejected.",
        "pre": "Task details drawer is open.",
        "steps": [
            ("Step 1", "Click \"Add Subtask\" input field and press Enter without entering any characters.", "Input field is focused but no list item is created."),
            ("Step 2", "Inspect the input validation state.", "A temporary red warning border or tooltip appears showing \"Subtask title cannot be empty\".")
        ]
    },
    {
        "name": "TC032_Sys_Pos_AddSubtaskMinTitle",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate adding a subtask with exactly 1 character (lower bound).",
        "pre": "Task details drawer is open.",
        "steps": [
            ("Step 1", "Type a single character \"X\" into the subtask input and press Enter.", "Subtask \"X\" is successfully created in the database and loaded in list."),
            ("Step 2", "Verify drawer presentation.", "The subtask is rendered with description \"X\" and an unchecked checkbox.")
        ]
    },
    {
        "name": "TC033_Sys_Pos_AddSubtaskMaxTitle",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate adding a subtask with a title of exactly 255 characters (upper bound).",
        "pre": "Task details drawer is open.",
        "steps": [
            ("Step 1", "Input a 255-character title in the subtask field and press Enter.", "Subtask is created successfully and fits neatly in the drawer bounds."),
            ("Step 2", "Verify database persistence.", "The subtask title is stored and loaded as exactly 255 characters with no trailing truncations.")
        ]
    },
    {
        "name": "TC034_Sys_Neg_AddSubtaskExceedMaxTitle",
        "pos_neg": "Negative",
        "type": "System",
        "desc": "Validate that adding a subtask with 256 characters is restricted.",
        "pre": "Task details drawer is open.",
        "steps": [
            ("Step 1", "Attempt to type a 256-character title into the subtask input field.", "Input box prevents typing past 255 characters, or displays warning indicator \"256/255\"."),
            ("Step 2", "Press Enter.", "The form restricts submission or truncates the input string to exactly 255 characters.")
        ]
    },
    {
        "name": "TC035_Sys_Pos_CreateTaskWithZeroTags",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate creating a task without attaching any tags (lower bound).",
        "pre": "\"Add Task\" modal is open.",
        "steps": [
            ("Step 1", "Fill out a valid Title and leave the tags input field empty.", "No tag badges are displayed in the form."),
            ("Step 2", "Click the \"Create\" button.", "Task is created successfully. Task card renders with no tag container.")
        ]
    },
    {
        "name": "TC036_Sys_Pos_CreateTaskWithMaxTags",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate task creation with exactly 10 tags (upper bound).",
        "pre": "\"Add Task\" modal is open.",
        "steps": [
            ("Step 1", "Enter exactly 10 unique tags sequentially in the tags field.", "10 tag badges are displayed. The tags text input is disabled/hidden."),
            ("Step 2", "Click the \"Create\" button.", "Task is created successfully. Task card renders all 10 badges within the card tag row.")
        ]
    },
    {
        "name": "TC037_Sys_Neg_CreateTaskExceedMaxTags",
        "pos_neg": "Negative",
        "type": "System",
        "desc": "Validate that adding an 11th tag is blocked.",
        "pre": "\"Add Task\" modal is open; 10 tags are active.",
        "steps": [
            ("Step 1", "Attempt to type an 11th tag value.", "Tag input box remains disabled with tooltip: \"Tag limit (10) reached\"."),
            ("Step 2", "Submit a task creation API request containing 11 tags.", "API server rejects request, returning `400 Bad Request` with error \"Cannot exceed 10 tags per task\".")
        ]
    },
    {
        "name": "TC038_Sys_Pos_CreateTaskMinTagLength",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate creating a tag containing exactly 1 character (lower bound).",
        "pre": "\"Add Task\" modal is open.",
        "steps": [
            ("Step 1", "Type \"Q\" in the tag input field and press Enter.", "A tag badge displaying \"Q\" is added to the form."),
            ("Step 2", "Click the \"Create\" button.", "Task is saved. Task card shows badge \"Q\" in the tag list.")
        ]
    },
    {
        "name": "TC039_Sys_Pos_CreateTaskMaxTagLength",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate creating a tag containing exactly 50 characters (upper bound).",
        "pre": "\"Add Task\" modal is open.",
        "steps": [
            ("Step 1", "Type a tag name containing exactly 50 characters and press Enter.", "A tag badge displaying exactly 50 characters is added successfully."),
            ("Step 2", "Click the \"Create\" button.", "Task is saved. The tag card shows the complete 50-character tag.")
        ]
    },
    {
        "name": "TC040_Sys_Neg_CreateTaskExceedMaxTagLength",
        "pos_neg": "Negative",
        "type": "System",
        "desc": "Validate that entering a tag title > 50 characters is blocked.",
        "pre": "\"Add Task\" modal is open.",
        "steps": [
            ("Step 1", "Attempt to input a tag name of 51 characters in the tag input.", "Input blocks input past 50 characters, or displays warning error \"Tag length cannot exceed 50 characters\"."),
            ("Step 2", "Press Enter.", "Form blocks tag creation or automatically truncates the tag to 50 characters.")
        ]
    },
    {
        "name": "TC041_Sys_Pos_CreateTaskUnicodeEmojis",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate task creation with unicode and emoji symbols in task title.",
        "pre": "\"Add Task\" modal is open.",
        "steps": [
            ("Step 1", "Type \"🚀 Deploy v1.4 codebase 🛡️\" as the task title.", "Title input displays emojis and unicode symbols correctly."),
            ("Step 2", "Click the \"Create\" button.", "Task is successfully saved. Emojis render correctly on the dashboard task card and task details drawer.")
        ]
    },
    {
        "name": "TC042_Sys_Pos_CreateTaskXSSSanitization",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate that XSS script payloads in task descriptions are sanitized.",
        "pre": "\"Add Task\" modal is open.",
        "steps": [
            ("Step 1", "Enter a valid Title and paste `<script>alert('XSS')</script><img src=\"x\" onerror=\"alert(1)\">` into the description.", "Text is accepted literally in the text area."),
            ("Step 2", "Click \"Create\", and click the new task card to open the Details drawer.", "Drawer renders description safely as literal text string; no script runs, showing solid sanitization.")
        ]
    },
    {
        "name": "TC043_Sys_Pos_CreateTaskSQLInjectionPrevention",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate that SQL injection payloads are treated as literal text values.",
        "pre": "\"Add Task\" modal is open.",
        "steps": [
            ("Step 1", "Enter `' OR 1=1; DROP TABLE tbl_tasks; --` in the task Title input field.", "String is entered literally."),
            ("Step 2", "Click \"Create\" button.", "Task is created successfully with the injection payload as its literal title. Database integrity is preserved.")
        ]
    },
    {
        "name": "TC044_Sys_Neg_CreateTaskNonexistentProject",
        "pos_neg": "Negative",
        "type": "API",
        "desc": "Validate that task creation fails when selecting a nonexistent project ID.",
        "pre": "User has authenticated and obtained valid bearer token; using API client.",
        "steps": [
            ("Step 1", "Send a POST request to `/api/v1/tasks` with project_id set to \"999999\" (nonexistent).", "API checks project association."),
            ("Step 2", "Inspect response status code and body.", "Server returns `400 Bad Request` or `404 Not Found` with message: \"Project not found\".")
        ]
    },
    {
        "name": "TC045_Sys_Pos_CreateTaskDefaultPriority",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate that task creation defaults to \"Medium\" priority when none is specified.",
        "pre": "\"Add Task\" modal is open.",
        "steps": [
            ("Step 1", "Enter a valid Title, but leave the priority selector default.", "Priority selector field displays no high/low overrides."),
            ("Step 2", "Click \"Create\" button.", "Task is created. Dashboard task card displays a grey \"Medium\" priority badge by default.")
        ]
    },
    {
        "name": "TC046_Sys_Neg_RegisterUsernameMinMinusOne",
        "pos_neg": "Negative",
        "type": "System",
        "desc": "Validate that registering a username of exactly 2 characters (below min length 3) is rejected.",
        "pre": "User is on the registration page (`/register`).",
        "steps": [
            ("Step 1", "Navigate to registration page (`/register`).", "Registration page loads with form."),
            ("Step 2", "Fill in email, username \"ab\" (2 characters), password.", "Username field shows \"ab\"."),
            ("Step 3", "Click \"Sign Up\".", "Form is blocked. Validation message \"Username must be at least 3 characters\" is shown below the username field.")
        ]
    },
    {
        "name": "TC047_Sys_Pos_RegisterUsernameMin",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate registering a username of exactly 3 characters (lower bound).",
        "pre": "User is on the registration page; no account exists with target username/email.",
        "steps": [
            ("Step 1", "Navigate to registration page (`/register`).", "Registration page loads successfully."),
            ("Step 2", "Fill in a unique email, username \"abc\" (3 characters), and valid password.", "Input fields populated correctly."),
            ("Step 3", "Click \"Sign Up\".", "User account created successfully, redirected to Dashboard.")
        ]
    },
    {
        "name": "TC048_Sys_Pos_RegisterUsernameMax",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate registering a username of exactly 50 characters (upper bound).",
        "pre": "User is on registration page.",
        "steps": [
            ("Step 1", "Navigate to registration page (`/register`).", "Registration page loads successfully."),
            ("Step 2", "Input unique email, a 50-character username, and valid password.", "Input fields populated."),
            ("Step 3", "Click \"Sign Up\".", "User account created successfully, redirected to Dashboard.")
        ]
    },
    {
        "name": "TC049_Sys_Neg_RegisterUsernameMaxPlusOne",
        "pos_neg": "Negative",
        "type": "System",
        "desc": "Validate registering a username of 51 characters (exceeding max 50) is blocked.",
        "pre": "User is on registration page.",
        "steps": [
            ("Step 1", "Navigate to registration page (`/register`).", "Registration page loads successfully."),
            ("Step 2", "Attempt to input a 51-character username, unique email, and password.", "Username input text displays the typed characters."),
            ("Step 3", "Click \"Sign Up\".", "Submission is blocked. Validation message \"Username cannot exceed 50 characters\" appears.")
        ]
    },
    {
        "name": "TC050_Sys_Neg_RegisterPasswordMinMinusOne",
        "pos_neg": "Negative",
        "type": "System",
        "desc": "Validate registering a password of exactly 7 characters (below min length 8) is rejected.",
        "pre": "User is on registration page.",
        "steps": [
            ("Step 1", "Navigate to registration page (`/register`).", "Registration page loads successfully."),
            ("Step 2", "Input unique email, valid username, and password \"pwd1234\" (7 characters).", "Form is populated."),
            ("Step 3", "Click \"Sign Up\".", "Submission blocked. Validation message \"Password must be at least 8 characters\" appears below password field.")
        ]
    },
    {
        "name": "TC051_Sys_Pos_RegisterPasswordMin",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate registering a password of exactly 8 characters (lower bound).",
        "pre": "User is on registration page.",
        "steps": [
            ("Step 1", "Navigate to registration page (`/register`).", "Registration page loads successfully."),
            ("Step 2", "Input unique email, valid username, and password \"pwd12345\" (8 characters).", "Form is populated."),
            ("Step 3", "Click \"Sign Up\".", "User account created successfully, redirected to Dashboard.")
        ]
    },
    {
        "name": "TC052_Sys_Pos_RegisterPasswordMax",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate registering a password of exactly 128 characters (upper bound).",
        "pre": "User is on registration page.",
        "steps": [
            ("Step 1", "Navigate to registration page (`/register`).", "Registration page loads successfully."),
            ("Step 2", "Input unique email, valid username, and a 128-character password.", "Form is populated."),
            ("Step 3", "Click \"Sign Up\".", "User account created successfully, redirected to Dashboard.")
        ]
    },
    {
        "name": "TC053_Sys_Neg_RegisterPasswordMaxPlusOne",
        "pos_neg": "Negative",
        "type": "System",
        "desc": "Validate registering a password of 129 characters (exceeding max 128) is blocked.",
        "pre": "User is on registration page.",
        "steps": [
            ("Step 1", "Navigate to registration page (`/register`).", "Registration page loads successfully."),
            ("Step 2", "Attempt to input a 129-character password.", "Form is populated with input password."),
            ("Step 3", "Click \"Sign Up\".", "Submission blocked. Validation message \"Password cannot exceed 128 characters\" appears.")
        ]
    },
    {
        "name": "TC054_Sys_Pos_RegisterEmailMax",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate registering an email of exactly 254 characters (upper bound under RFC standard).",
        "pre": "User is on registration page.",
        "steps": [
            ("Step 1", "Navigate to registration page (`/register`).", "Registration page loads successfully."),
            ("Step 2", "Input a valid formatted email address of exactly 254 characters, valid username, and password.", "Form populated."),
            ("Step 3", "Click \"Sign Up\".", "User account created successfully, redirected to Dashboard.")
        ]
    },
    {
        "name": "TC055_Sys_Neg_RegisterEmailMaxPlusOne",
        "pos_neg": "Negative",
        "type": "System",
        "desc": "Validate registering an email of 255 characters (exceeding max 254) is blocked.",
        "pre": "User is on registration page.",
        "steps": [
            ("Step 1", "Navigate to registration page (`/register`).", "Registration page loads successfully."),
            ("Step 2", "Attempt to input a 255-character email address.", "Email field displays the typed email."),
            ("Step 3", "Click \"Sign Up\".", "Server/client rejects request. Error message \"Email cannot exceed 254 characters\" is shown.")
        ]
    },
    {
        "name": "TC056_Sys_Pos_CreateProjectMinName",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate creating a project with a name of exactly 1 character (lower bound).",
        "pre": "User is logged in and viewing Dashboard.",
        "steps": [
            ("Step 1", "Click the \"+\" action button next to \"Projects\" in sidebar.", "\"Create Project\" Modal opens."),
            ("Step 2", "Input project name \"P\" (1 character).", "Field populated with \"P\"."),
            ("Step 3", "Click \"Save\".", "Modal closes, project \"P\" is created and rendered in sidebar.")
        ]
    },
    {
        "name": "TC057_Sys_Pos_CreateProjectMaxName",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate creating a project with a name of exactly 50 characters (upper bound).",
        "pre": "User is logged in and viewing Dashboard.",
        "steps": [
            ("Step 1", "Click \"+\" next to \"Projects\".", "\"Create Project\" Modal opens."),
            ("Step 2", "Enter a 50-character string in the Project Name field.", "Name field shows character limit 50/50."),
            ("Step 3", "Click \"Save\".", "Project is created and full 50-character name is rendered.")
        ]
    },
    {
        "name": "TC058_Sys_Neg_CreateProjectExceedMaxName",
        "pos_neg": "Negative",
        "type": "System",
        "desc": "Validate that creating a project with a name of 51 characters is blocked.",
        "pre": "User is logged in and viewing Dashboard.",
        "steps": [
            ("Step 1", "Click \"+\" next to \"Projects\".", "\"Create Project\" Modal opens."),
            ("Step 2", "Attempt to type a 51-character project name.", "Project name input field displays the typed name."),
            ("Step 3", "Click \"Save\".", "Form submission is blocked. Validation message \"Project name must be 50 characters or less\" appears.")
        ]
    },
    {
        "name": "TC059_Sys_Pos_CreateProjectUnderCapacityLimit",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate creating a project when the user has exactly 19 projects (creating the 20th project).",
        "pre": "User is logged in; has exactly 19 active projects.",
        "steps": [
            ("Step 1", "Click \"+\" next to \"Projects\".", "\"Create Project\" Modal opens."),
            ("Step 2", "Enter a valid project name.", "Project details populated."),
            ("Step 3", "Click \"Save\".", "Project is created successfully, making total project count exactly 20.")
        ]
    },
    {
        "name": "TC060_Sys_Neg_CreateProjectExceedCapacityLimit",
        "pos_neg": "Negative",
        "type": "System",
        "desc": "Validate that creating a 21st project is rejected by the backend.",
        "pre": "User has exactly 20 active projects.",
        "steps": [
            ("Step 1", "Click \"+\" next to \"Projects\".", "\"Create Project\" Modal opens."),
            ("Step 2", "Enter a valid project name and click \"Save\".", "Modal shows loading spinner then displays server error."),
            ("Step 3", "Inspect the displayed error banner.", "Server rejects creation with message \"Cannot exceed 20 projects per user\".")
        ]
    },
    {
        "name": "TC061_Sys_Pos_CreateTaskUnderCapacityLimit",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate creating a task when the user has exactly 999 tasks (creating the 1000th task).",
        "pre": "User has exactly 999 active tasks in their account.",
        "steps": [
            ("Step 1", "Click \"Add Task\" button at header of the Tasks view.", "\"Add Task\" modal opens."),
            ("Step 2", "Input valid task title and click \"Create\" button.", "Form submitted."),
            ("Step 3", "Verify task creation.", "Task created successfully, bringing the user's total task count to 1000.")
        ]
    },
    {
        "name": "TC062_Sys_Neg_CreateTaskExceedCapacityLimit",
        "pos_neg": "Negative",
        "type": "System",
        "desc": "Validate that creating a 1001st task is rejected by the backend.",
        "pre": "User has exactly 1000 active tasks in their account.",
        "steps": [
            ("Step 1", "Click \"Add Task\" button to trigger task creation modal.", "\"Add Task\" modal opens."),
            ("Step 2", "Input valid task title and click \"Create\".", "Modal shows error spinner."),
            ("Step 3", "Inspect response/alert message.", "Server rejects request with error \"Cannot exceed 1000 tasks per user\".")
        ]
    },
    {
        "name": "TC063_Sys_Pos_CreateTaskWithTenTags",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate task creation with exactly 10 tags (upper bound).",
        "pre": "User has active tags available.",
        "steps": [
            ("Step 1", "Click \"Add Task\" to open task modal.", "\"Add Task\" modal opens."),
            ("Step 2", "Add exactly 10 unique tags to the task form.", "10 tag badges are displayed on the form."),
            ("Step 3", "Click \"Create\".", "Task is created with all 10 tags bound successfully.")
        ]
    },
    {
        "name": "TC064_Sys_Neg_CreateTaskWithElevenTags",
        "pos_neg": "Negative",
        "type": "System",
        "desc": "Validate that adding an 11th tag to a task is blocked by the backend/UI.",
        "pre": "Task creation modal is open; 10 tags are already selected.",
        "steps": [
            ("Step 1", "Try to type or select an 11th tag.", "Tag input is disabled or displays a \"Max tags reached\" warning."),
            ("Step 2", "Submit an API request with 11 tags via an API client.", "Server processes request."),
            ("Step 3", "Inspect response status.", "Returns HTTP 400 with message \"Cannot exceed 10 tags per task\".")
        ]
    },
    {
        "name": "TC065_Sys_Pos_CreateTagUnderCapacityLimit",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate creating tags when user has exactly 49 tags total (creating the 50th tag).",
        "pre": "User has exactly 49 tags registered in their account.",
        "steps": [
            ("Step 1", "Click \"Add Task\" button and navigate to tag creation input.", "Form active."),
            ("Step 2", "Input a new unique tag \"FinalTag\" (making the 50th tag) and press Enter.", "Tag is accepted."),
            ("Step 3", "Click \"Create\" to save the task.", "Tag and task are successfully created. Total tag count is 50.")
        ]
    },
    {
        "name": "TC066_Sys_Neg_CreateTagExceedCapacityLimit",
        "pos_neg": "Negative",
        "type": "System",
        "desc": "Validate that creating a 51st tag is rejected by the server.",
        "pre": "User has exactly 50 tags total.",
        "steps": [
            ("Step 1", "Click \"Add Task\" button to open modal.", "Modal opens."),
            ("Step 2", "Type a new tag name \"ExceedTag\" (which would be 51st tag) and press Enter.", "Tag badge displays."),
            ("Step 3", "Click \"Create\".", "Server rejects request with HTTP 400 \"Cannot exceed 50 tags per user\".")
        ]
    },
    {
        "name": "TC067_Sys_Pos_CreateTaskWithFiftySubtasks",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate creating a task containing exactly 50 subtasks (upper bound).",
        "pre": "Task creation modal is open.",
        "steps": [
            ("Step 1", "Input valid task title and add exactly 50 subtasks in the modal.", "Form displays 50 subtasks."),
            ("Step 2", "Click the \"Create\" button.", "Form is submitted."),
            ("Step 3", "Observe dashboard card.", "Task card successfully renders with \"0/50\" subtasks progress.")
        ]
    },
    {
        "name": "TC068_Sys_Neg_CreateTaskWithFiftyOneSubtasks",
        "pos_neg": "Negative",
        "type": "System",
        "desc": "Validate that creating a task with 51 subtasks is blocked.",
        "pre": "Task creation modal is open; 50 subtasks are already filled.",
        "steps": [
            ("Step 1", "Attempt to add a 51st subtask via the UI input.", "Add subtask input field is disabled/greyed out."),
            ("Step 2", "Submit a POST request with 51 nested subtasks via API client.", "Request processed."),
            ("Step 3", "Inspect response details.", "Server returns HTTP 400 Bad Request with \"Cannot exceed 50 subtasks per task\".")
        ]
    },
    {
        "name": "TC069_Sys_Pos_CreateTagMinName",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate creating a tag with exactly 1 character (lower bound).",
        "pre": "Task creation modal is open.",
        "steps": [
            ("Step 1", "Type a single character \"Z\" in the tag input field and press Enter.", "Tag badge \"Z\" is created."),
            ("Step 2", "Click the \"Create\" button.", "Task is successfully created."),
            ("Step 3", "Verify the tag card on Dashboard.", "Tag badge showing \"Z\" is displayed on task card.")
        ]
    },
    {
        "name": "TC070_Sys_Pos_CreateTagMaxName",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate creating a tag with exactly 50 characters (upper bound).",
        "pre": "Task creation modal is open.",
        "steps": [
            ("Step 1", "Enter a tag of exactly 50 characters in the tag input.", "Tag badge is rendered correctly."),
            ("Step 2", "Click the \"Create\" button.", "Task is created."),
            ("Step 3", "Verify drawer rendering.", "Full 50-character tag name is displayed in task details drawer.")
        ]
    },
    {
        "name": "TC071_Sys_Neg_CreateTagExceedMaxName",
        "pos_neg": "Negative",
        "type": "System",
        "desc": "Validate that creating a tag with 51 characters is blocked.",
        "pre": "Task creation modal is open.",
        "steps": [
            ("Step 1", "Attempt to enter a 51-character tag name.", "Tag name input displays the typed tag name."),
            ("Step 2", "Submit an API request with a 51-character tag.", "Server processes request."),
            ("Step 3", "Inspect response status code.", "Server returns HTTP 422/400 validation error on tag name length.")
        ]
    },
    {
        "name": "TC072_Sys_Neg_IdempotencyKeyMinMinusOne",
        "pos_neg": "Negative",
        "type": "API",
        "desc": "Validate that API requests with `X-Idempotency-Key` shorter than 8 characters are rejected.",
        "pre": "User is authenticated with a valid JWT token; API client ready.",
        "steps": [
            ("Step 1", "Formulate a POST request to `/api/v1/tasks` with header `X-Idempotency-Key` set to \"abc1234\" (7 characters).", "Header attached."),
            ("Step 2", "Send the request to the server.", "Server middleware intercepts request."),
            ("Step 3", "Verify response body.", "Returns HTTP 400 Bad Request with detail: \"Invalid X-Idempotency-Key format. Must be at least 8 characters.\"")
        ]
    },
    {
        "name": "TC073_Sys_Pos_IdempotencyKeyMin",
        "pos_neg": "Positive",
        "type": "API",
        "desc": "Validate that API requests with `X-Idempotency-Key` of exactly 8 characters (lower bound) are accepted.",
        "pre": "User is authenticated with a valid JWT token.",
        "steps": [
            ("Step 1", "Formulate a POST request to `/api/v1/tasks` with header `X-Idempotency-Key` set to \"abc12345\" (8 characters).", "Header attached."),
            ("Step 2", "Send the request to the server.", "Server processes request."),
            ("Step 3", "Inspect response status code.", "Server returns HTTP 201 Created. Response cached successfully.")
        ]
    },
    {
        "name": "TC074_Sys_Pos_CreateTaskMinDescription",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate task creation with a description of exactly 1 character (lower bound).",
        "pre": "\"Add Task\" modal is open.",
        "steps": [
            ("Step 1", "Input valid task Title and type a single character \"d\" in Description.", "Description displays \"d\"."),
            ("Step 2", "Click the \"Create\" button.", "Task created successfully."),
            ("Step 3", "Open details drawer.", "Description displays exactly \"d\".")
        ]
    },
    {
        "name": "TC075_Sys_Pos_AddSubtaskMinName",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate adding a subtask with a title of exactly 1 character (lower bound).",
        "pre": "Task details drawer is open.",
        "steps": [
            ("Step 1", "Type a single character \"s\" in the subtask field.", "Subtask input displays \"s\"."),
            ("Step 2", "Press Enter.", "Subtask is created, database is synced."),
            ("Step 3", "Verify subtask list.", "Subtask is rendered with title \"s\" and an unchecked checkbox.")
        ]
    },
    {
        "name": "TC076_Sys_Pos_AddSubtaskMaxName",
        "pos_neg": "Positive",
        "type": "System",
        "desc": "Validate adding a subtask with a title of exactly 255 characters (upper bound).",
        "pre": "Task details drawer is open.",
        "steps": [
            ("Step 1", "Paste a 255-character string in the subtask input.", "Input displays 255-character string."),
            ("Step 2", "Press Enter.", "Subtask is created successfully."),
            ("Step 3", "Verify subtask rendering.", "Subtask renders full 255 characters in details list.")
        ]
    },
    {
        "name": "TC077_Sys_Neg_AddSubtaskExceedMaxName",
        "pos_neg": "Negative",
        "type": "System",
        "desc": "Validate that adding a subtask with a title exceeding 255 characters (e.g. 256 chars) is rejected.",
        "pre": "Task details drawer is open.",
        "steps": [
            ("Step 1", "Attempt to paste a 256-character string into the subtask input.", "Subtask input displays the pasted string."),
            ("Step 2", "Press Enter to submit.", "Client validates input length. Submission is blocked or title is truncated."),
            ("Step 3", "Submit a POST request with a 256-character subtask title via API.", "Server rejects with HTTP 422 validation error.")
        ]
    }
]

# Generate Markdown Content
lines = [
    "# Task Buddy — Comprehensive System Test Cases",
    "",
    "This document defines the system-level and integration-level test cases for the Task Buddy application. All test scenarios strictly conform to the QA specification guidelines: zero-padded scenario naming, 8-column design structure, and blank metadata columns on subsequent rows to denote visual nesting.",
    "",
    "---",
    "",
    "## 📋 System Test Cases (Design-Time Specification)",
    "",
    "| TEST CASE NAME | POSITIVE/ NEGATIVE | TYPE | DESCRIPTION | PRE-CONDITION | TEST STEP NO. | TEST STEP DESCRIPTION | TEST EXPECTED RESULT |",
    "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |"
]

for tc in testcases:
    name = tc["name"]
    pos_neg = tc["pos_neg"]
    tc_type = tc["type"]
    desc = tc["desc"]
    pre = tc["pre"]
    for i, (step_no, step_desc, expected) in enumerate(tc["steps"]):
        if i == 0:
            # First row has all columns
            row = f"| `{name}` | {pos_neg} | {tc_type} | {desc} | {pre} | {step_no} | {step_desc} | {expected} |"
        else:
            # Subsequent rows have blank columns 1 to 5
            row = f"| | | | | | {step_no} | {step_desc} | {expected} |"
        lines.append(row)

lines.extend([
    "",
    "---",
    "",
    "## 🛠️ QA Verification Checklist",
    "",
    "Review all added test cases using this quality control gate before executing:",
    "",
    "- [ ] **Naming Schema**: Matches `TC[Number]_[Type]_[Pos/Neg]_[ActionCamelCase]`.",
    "- [ ] **Column Count**: Exactly 8 columns utilized for design.",
    "- [ ] **Step Nesting**: Rows 2+ of the same test case have empty columns for Columns 1 to 5 (`TEST CASE NAME` through `PRE-CONDITION`).",
    "- [ ] **Step Format**: Every step number is formatted exactly as `Step N`.",
    "- [ ] **Expected Results**: Written in verifiable terms (e.g., \"Toast appears\", \"Redirected to...\", \"RED alert is shown\").",
    ""
])

markdown_content = "\n".join(lines)

# Validation check
table_started = False
for line_no, line in enumerate(lines, 1):
    if line.startswith("| TEST CASE NAME |"):
        table_started = True
        continue
    if table_started and line.startswith("|"):
        # Verify column count
        cols = line.split("|")
        # Split by '|' on "| A | B | C | D | E | F | G | H |" gives 10 elements:
        # cols[0] is '', cols[9] is ''
        # cols[1] through cols[8] are the 8 columns
        if len(cols) != 10:
            raise AssertionError(f"Line {line_no} does not have exactly 8 columns (found {len(cols)-2}): {line}")

print("Validation PASSED! All rows have exactly 8 columns.")

# Write to backend docs path
backend_path = "c:\\Users\\admin\\OneDrive\\Documents\\GitHub\\task-buddy-backend\\docs\\system_test_cases.md"
os.makedirs(os.path.dirname(backend_path), exist_ok=True)
with open(backend_path, "w", encoding="utf-8") as f:
    f.write(markdown_content)
print(f"Successfully wrote to backend path: {backend_path}")

# Write to app data brain path
appdata_path = "C:\\Users\\admin\\.gemini\\antigravity\\brain\\be7e57ab-b0f0-47d4-9c30-7f0417e082fd\\system_test_cases.md"
os.makedirs(os.path.dirname(appdata_path), exist_ok=True)
with open(appdata_path, "w", encoding="utf-8") as f:
    f.write(markdown_content)
print(f"Successfully wrote to appdata path: {appdata_path}")
