<USER_REQUEST>
Looking closely at your logs, there is a very clear pattern of **infinite looping or rapid-fire duplicate requests** happening every time your frontend tries to modify data.

Specifically, whenever you hit a modifying endpoint (`PUT` or `DELETE`), your API immediately returns an **HTTP 400 Bad Request**, followed by a flood of repetitive `GET /api/v1/tasks/` and `GET /api/v1/tasks/3` requests in the exact same millisecond.

Here are the most likely reasons why your `PUT` and `DELETE` requests are failing with an HTTP 400 error:

---

## 1. Frontend State Synchronization Loop (The Log Flood)

Look at this snippet from your logs around `17:02:39` to `17:02:40`:

* A single frontend action triggers a `PUT /api/v1/tasks/3` which fails with a `400`.
* Immediately, the backend is bombarded with dozens of `GET` requests fetching the task list and task `3` over and over again.

<truncated 12731 bytes>