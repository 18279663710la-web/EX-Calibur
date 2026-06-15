_tasks: dict[str, dict] = {}


def save_task(task_id: str, task: dict):
    _tasks[task_id] = task


def load_task(task_id: str) -> dict | None:
    return _tasks.get(task_id)
