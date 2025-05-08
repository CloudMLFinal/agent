import asyncio
import os
from typing import Optional, Callable
from monitroing.package import LogLevel, MessagePackage
from .fixer import CodeFixer
from logger import logger

class CodeFixerQueue:
    _instance = None
    _initialized = False
    _loop = None

    def __new__(cls):
        """Create a new instance of the CodeFixerQueue(Singleton)"""	
        if cls._instance is None:
            cls._instance = super(CodeFixerQueue, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize the CodeFixer queue with worker count from environment"""
        if CodeFixerQueue._initialized:
            return
            
        # Get worker count from environment or use default
        self.max_workers = int(os.getenv("MAX_AGENT_NUM", "1"))
        self.queue = asyncio.Queue()
        self.workers = []
        self._stop_event = asyncio.Event()
        self._running = False
        self._start_task = None
        
        # Create event loop if not exists
        try:
            self._loop = asyncio.get_event_loop()
        except RuntimeError:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
        
        # Start the queue automatically
        if self._loop is not None:
            self._start_task = self._loop.create_task(self._auto_start())
        
        CodeFixerQueue._initialized = True
        logger.info(f"Initialized CodeFixerQueue with {self.max_workers} workers")

    async def _auto_start(self):
        """Automatically start the queue and keep it running"""
        while not self._stop_event.is_set():
            try:
                if not self._running:
                    await self.start()
                await asyncio.wait_for(self._stop_event.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Error in starting agent queue: {str(e)}")
                await asyncio.sleep(5)  # Wait 5 seconds before retrying

    def submit_job(self, pkg: MessagePackage, callback: Optional[Callable[[bool], None]] = None) -> None:
        """Submit a new job to the queue (synchronous version)
        Args:
            pkg: Message Package
            callback: Optional callback function to be called when job completes
        """
        if pkg.level in {LogLevel.INFO, LogLevel.DEBUG, LogLevel.WARNING}:
            return
        if self._loop is not None:
            if self._loop.is_running():
                asyncio.run_coroutine_threadsafe(self._submit_job_async(pkg, callback), self._loop)
            else:
                self._loop.run_until_complete(self._submit_job_async(pkg, callback))
        else:
            logger.error("Event loop not initialized")

    async def _submit_job_async(self, pkg: MessagePackage, callback: Optional[Callable[[bool], None]] = None) -> None:
        """Submit a new job to the queue (async version)"""
        await self.queue.put((pkg, callback))
        logger.info(f"Submitted new agent job")

    async def _worker(self) -> None:
        """Worker function that processes jobs from the queue"""
        while not self._stop_event.is_set():
            try:
                pkg, callback = await self.queue.get()
                try:
                    logger.info(f"Assign ticket to worker")
                    fixer = CodeFixer(pkg)
                    success = await fixer.run()
                    if callback:
                        callback(success)
                except Exception as e:
                    logger.error(f"Error processing job: {str(e)}")
                    if callback:
                        callback(False)
                finally:
                    logger.info(f"Agent Queue task done")
                    self.queue.task_done()
            except asyncio.CancelledError:
                break

    async def start(self) -> None:
        """Start the job queue workers"""
        if self._running:
            return

        self._running = True
        self._stop_event.clear()

        # Create worker tasks
        if self._loop is not None:
            self.workers = [
                self._loop.create_task(self._worker())
                for _ in range(self.max_workers)
            ]
            logger.info(f"Started {self.max_workers} workers")
        else:
            logger.error("Event loop not initialized")

    def stop(self) -> None:
        """Stop the job queue workers (synchronous version)"""
        if self._loop is not None:
            self._loop.run_until_complete(self._stop_async())
        else:
            logger.error("Event loop not initialized")

    async def _stop_async(self) -> None:
        """Stop the job queue workers (async version)"""
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        # Wait for all workers to complete
        if self.workers:
            await asyncio.gather(*self.workers, return_exceptions=True)
            self.workers.clear()

        # Wait for queue to be empty
        await self.queue.join()
        logger.info("Stopped all workers")

    async def shutdown(self):
        await self._stop_async()
        if self._start_task:
            self._start_task.cancel()
            try:
                await self._start_task
            except asyncio.CancelledError:
                pass

    @property
    def is_running(self) -> bool:
        """Check if the queue is running"""
        return self._running

    @property
    def queue_size(self) -> int:
        """Get current queue size"""
        return self.queue.qsize() 