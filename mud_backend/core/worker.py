# mud_backend/core/worker.py
# NEW FILE: Handles heavy CPU tasks in separate processes
import multiprocessing
import time
from typing import Callable, Any

def _worker_process(input_queue, output_queue):
    """
    The logic running in the separate process.
    Waits for tasks, executes them, and returns results.
    """
    while True:
        try:
            task = input_queue.get()
            if task is None: # Sentinel to stop
                break
                
            task_id, func, args, kwargs = task
            
            try:
                # Execute the heavy function
                result = func(*args, **kwargs)
                output_queue.put((task_id, "success", result))
            except Exception as e:
                output_queue.put((task_id, "error", str(e)))
                
        except Exception as e:
            print(f"[WORKER ERROR] {e}")

class WorkerManager:
    def __init__(self, num_workers=1):
        self.input_queue = multiprocessing.Queue()
        self.output_queue = multiprocessing.Queue()
        self.workers = []
        self.num_workers = num_workers
        self.callbacks = {} # task_id -> callback_func

    def start(self):
        for _ in range(self.num_workers):
            p = multiprocessing.Process(
                target=_worker_process, 
                args=(self.input_queue, self.output_queue)
            )
            p.daemon = True
            p.start()
            self.workers.append(p)
        print(f"[WORKER] Started {self.num_workers} background worker processes.")

    def submit_task(self, task_id: str, func: Callable, callback: Callable, *args, **kwargs):
        """
        Submits a task to the worker pool.
        func: The heavy function to run (Must be pickle-able, i.e., top-level function)
        callback: Function to call with the result on the main thread
        """
        self.callbacks[task_id] = callback
        self.input_queue.put((task_id, func, args, kwargs))

    def check_results(self):
        """
        Call this from the main game loop to process completed tasks.
        """
        while not self.output_queue.empty():
            try:
                task_id, status, data = self.output_queue.get_nowait()
                callback = self.callbacks.pop(task_id, None)
                if callback:
                    callback(status, data)
            except:
                break

    def stop(self):
        for _ in range(self.num_workers):
            self.input_queue.put(None)
        for p in self.workers:
            p.join()