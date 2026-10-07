// Run via mongosh or Atlas UI. See docs/DATABASE_DESIGN.md §10.
db.videos.createIndex({ youtube_id: 1 }, { unique: true });
db.videos.createIndex({ status: 1, created_at: -1 });
db.videos.createIndex({ created_at: -1 });
db.flashcards.createIndex({ video_id: 1, timestamp_sec: 1 });
db.analytics.createIndex({ video_id: 1 }, { unique: true });
db.processing_jobs.createIndex({ video_id: 1, started_at: -1 }, { expireAfterSeconds: 7776000 }); // 90d TTL
