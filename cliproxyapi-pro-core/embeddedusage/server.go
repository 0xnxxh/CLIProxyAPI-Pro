package embeddedusage

import (
	"bufio"
	"encoding/json"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/router-for-me/CLIProxyAPI/v6/internal/embeddedusage/internalusage"
)

const accountInspectionScheduleExportRecordType = "account_inspection_schedule"

type usageStreamEvent = internalusage.Payload

type accountInspectionScheduleExportRecord struct {
	RecordType string          `json:"record_type"`
	Version    int             `json:"version"`
	Schedule   json.RawMessage `json:"schedule"`
	ExportedAt int64           `json:"exported_at_ms"`
}

type Server struct {
	cfg   Config
	store *Store
}

func NewServer(cfg Config, store *Store) *Server {
	return &Server{cfg: cfg, store: store}
}

func RegisterGinRoutes(group *gin.RouterGroup) {
	server := defaultServer()
	if server == nil {
		group.GET("", func(c *gin.Context) {
			c.JSON(http.StatusServiceUnavailable, gin.H{"error": "usage service is not available"})
		})
		group.GET("/export", func(c *gin.Context) {
			c.JSON(http.StatusServiceUnavailable, gin.H{"error": "usage service is not available"})
		})
		group.POST("/import", func(c *gin.Context) {
			c.JSON(http.StatusServiceUnavailable, gin.H{"error": "usage service is not available"})
		})
		group.GET("/status", func(c *gin.Context) {
			c.JSON(http.StatusServiceUnavailable, gin.H{"error": "usage service is not available"})
		})
		group.GET("/events", func(c *gin.Context) {
			c.JSON(http.StatusServiceUnavailable, gin.H{"error": "usage service is not available"})
		})
		group.GET("/stream", func(c *gin.Context) {
			c.JSON(http.StatusServiceUnavailable, gin.H{"error": "usage service is not available"})
		})
		group.GET("/quota-cache", func(c *gin.Context) {
			c.JSON(http.StatusServiceUnavailable, gin.H{"error": "usage service is not available"})
		})
		group.PUT("/quota-cache", func(c *gin.Context) {
			c.JSON(http.StatusServiceUnavailable, gin.H{"error": "usage service is not available"})
		})
		group.DELETE("/quota-cache", func(c *gin.Context) {
			c.JSON(http.StatusServiceUnavailable, gin.H{"error": "usage service is not available"})
		})
		group.GET("/model-prices", func(c *gin.Context) {
			c.JSON(http.StatusServiceUnavailable, gin.H{"error": "usage service is not available"})
		})
		group.PUT("/model-prices", func(c *gin.Context) {
			c.JSON(http.StatusServiceUnavailable, gin.H{"error": "usage service is not available"})
		})
		return
	}
	server.RegisterGinRoutes(group)
}

func (s *Server) RegisterGinRoutes(group *gin.RouterGroup) {
	group.GET("", s.handleUsage)
	group.GET("/export", s.handleUsageExport)
	group.POST("/import", s.handleUsageImport)
	group.GET("/status", s.handleStatus)
	group.GET("/events", s.handleUsageEvents)
	group.GET("/stream", s.handleUsageStream)
	group.GET("/quota-cache", s.handleQuotaCacheGet)
	group.PUT("/quota-cache", s.handleQuotaCachePut)
	group.DELETE("/quota-cache", s.handleQuotaCacheDelete)
	group.GET("/model-prices", s.handleModelPricesGet)
	group.PUT("/model-prices", s.handleModelPricesPut)
}

func parseQueryInt64(c *gin.Context, key string, fallback int64) int64 {
	value := strings.TrimSpace(c.Query(key))
	if value == "" {
		return fallback
	}
	parsed, err := strconv.ParseInt(value, 10, 64)
	if err != nil || parsed < 0 {
		return fallback
	}
	return parsed
}

func parseQueryInt(c *gin.Context, key string, fallback int) int {
	value := strings.TrimSpace(c.Query(key))
	if value == "" {
		return fallback
	}
	parsed, err := strconv.Atoi(value)
	if err != nil {
		return fallback
	}
	return parsed
}
func (s *Server) handleUsage(c *gin.Context) {
	events, err := s.store.RecentEvents(c.Request.Context(), s.cfg.QueryLimit)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, internalusage.BuildPayload(events))
}

func (s *Server) handleUsageEvents(c *gin.Context) {
	afterID := parseQueryInt64(c, "after_id", 0)
	limit := parseQueryInt(c, "limit", s.cfg.BatchSize)
	events, err := s.store.EventsAfter(c.Request.Context(), afterID, limit)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, internalusage.BuildPayload(events))
}

func (s *Server) handleUsageStream(c *gin.Context) {
	flusher, ok := c.Writer.(http.Flusher)
	if !ok {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "streaming is not supported"})
		return
	}

	lastID := parseQueryInt64(c, "after_id", 0)
	initialEvents, err := s.store.EventsAfter(c.Request.Context(), lastID, s.cfg.BatchSize)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}

	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache")
	c.Header("Connection", "keep-alive")
	c.Header("X-Accel-Buffering", "no")

	ticker := time.NewTicker(time.Second)
	defer ticker.Stop()

	writeEvent := func(name string, payload usageStreamEvent) bool {
		data, err := json.Marshal(payload)
		if err != nil {
			return false
		}
		if _, err := fmt.Fprintf(c.Writer, "event: %s\ndata: %s\n\n", name, data); err != nil {
			return false
		}
		flusher.Flush()
		return true
	}

	if len(initialEvents) == 0 {
		if !writeEvent("ready", internalusage.BuildPayload(nil)) {
			return
		}
	} else {
		payload := internalusage.BuildPayload(initialEvents)
		lastID = payload.LatestID
		if !writeEvent("usage", payload) {
			return
		}
	}

	for {
		select {
		case <-c.Request.Context().Done():
			return
		case <-ticker.C:
			events, err := s.store.EventsAfter(c.Request.Context(), lastID, s.cfg.BatchSize)
			if err != nil {
				return
			}
			if len(events) == 0 {
				if _, err := fmt.Fprint(c.Writer, ": keepalive\n\n"); err != nil {
					return
				}
				flusher.Flush()
				continue
			}
			payload := internalusage.BuildPayload(events)
			lastID = payload.LatestID
			if !writeEvent("usage", payload) {
				return
			}
		}
	}
}

func (s *Server) handleUsageExport(c *gin.Context) {
	data, err := s.store.ExportJSONL(c.Request.Context())
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	if accountInspectionScheduleExporter != nil {
		schedule, ok, err := accountInspectionScheduleExporter()
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
			return
		}
		if ok {
			line, err := json.Marshal(accountInspectionScheduleExportRecord{
				RecordType: accountInspectionScheduleExportRecordType,
				Version:    1,
				Schedule:   schedule,
				ExportedAt: time.Now().UnixMilli(),
			})
			if err != nil {
				c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
				return
			}
			data = append(data, line...)
			data = append(data, '\n')
		}
	}
	c.Header("Content-Type", "application/x-ndjson")
	c.Header("Content-Disposition", `attachment; filename="usage-events.jsonl"`)
	_, _ = c.Writer.Write(data)
}

func (s *Server) handleUsageImport(c *gin.Context) {
	reader := bufio.NewScanner(c.Request.Body)
	reader.Buffer(make([]byte, 64*1024), 10*1024*1024)
	events := make([]internalusage.Event, 0)
	var modelPrices map[string]ModelPrice
	modelPriceRecords := 0
	var quotaEntries []QuotaCacheEntry
	quotaCacheRecords := 0
	var accountInspectionSchedule json.RawMessage
	accountInspectionScheduleRecords := 0
	failed := 0
	for reader.Scan() {
		line := strings.TrimSpace(reader.Text())
		if line == "" {
			continue
		}
		if schedule, ok, err := parseAccountInspectionScheduleImportRecord([]byte(line)); err != nil {
			failed++
			continue
		} else if ok {
			accountInspectionSchedule = schedule
			accountInspectionScheduleRecords++
			continue
		}
		if prices, ok, err := parseModelPricesImportRecord([]byte(line)); err != nil {
			failed++
			continue
		} else if ok {
			modelPrices = prices
			modelPriceRecords++
			continue
		}
		if entries, ok, err := parseQuotaCacheImportRecord([]byte(line)); err != nil {
			failed++
			continue
		} else if ok {
			quotaEntries = append(quotaEntries, entries...)
			quotaCacheRecords++
			continue
		}
		event, err := internalusage.NormalizeRaw([]byte(line))
		if err != nil {
			failed++
			continue
		}
		events = append(events, event)
	}
	if err := reader.Err(); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	result, err := s.store.InsertEvents(c.Request.Context(), events)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	if modelPrices != nil {
		if err := s.store.SetModelPrices(c.Request.Context(), modelPrices); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
			return
		}
	}
	if len(quotaEntries) > 0 {
		for _, entry := range quotaEntries {
			if err := s.store.SetQuotaCache(c.Request.Context(), entry); err != nil {
				c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
				return
			}
		}
	}
	if accountInspectionSchedule != nil && accountInspectionScheduleImporter != nil {
		if err := accountInspectionScheduleImporter(accountInspectionSchedule); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
			return
		}
	}
	c.JSON(http.StatusOK, gin.H{
		"added":                            result.Inserted,
		"skipped":                          result.Skipped,
		"total":                            len(events),
		"failed":                           failed,
		"modelPrices":                      len(modelPrices),
		"modelPriceRecords":                modelPriceRecords,
		"quotaCache":                       len(quotaEntries),
		"quotaCacheRecords":                quotaCacheRecords,
		"accountInspectionSchedule":        accountInspectionSchedule != nil,
		"accountInspectionScheduleRecords": accountInspectionScheduleRecords,
	})
}

func parseAccountInspectionScheduleImportRecord(raw []byte) (json.RawMessage, bool, error) {
	var header struct {
		RecordType string `json:"record_type"`
	}
	if err := json.Unmarshal(raw, &header); err != nil {
		return nil, false, err
	}
	if header.RecordType != accountInspectionScheduleExportRecordType {
		return nil, false, nil
	}

	var record accountInspectionScheduleExportRecord
	if err := json.Unmarshal(raw, &record); err != nil {
		return nil, true, err
	}
	if len(record.Schedule) == 0 {
		return nil, true, nil
	}
	return record.Schedule, true, nil
}

func parseQuotaCacheImportRecord(raw []byte) ([]QuotaCacheEntry, bool, error) {
	var header struct {
		RecordType string `json:"record_type"`
	}
	if err := json.Unmarshal(raw, &header); err != nil {
		return nil, false, err
	}
	if header.RecordType != quotaCacheExportRecordType {
		return nil, false, nil
	}

	var record quotaCacheExportRecord
	if err := json.Unmarshal(raw, &record); err != nil {
		return nil, true, err
	}
	return record.Entries, true, nil
}

func parseModelPricesImportRecord(raw []byte) (map[string]ModelPrice, bool, error) {
	var header struct {
		RecordType string `json:"record_type"`
	}
	if err := json.Unmarshal(raw, &header); err != nil {
		return nil, false, err
	}
	if header.RecordType != modelPricesExportRecordType {
		return nil, false, nil
	}

	var record modelPricesExportRecord
	if err := json.Unmarshal(raw, &record); err != nil {
		return nil, true, err
	}
	if record.Prices == nil {
		record.Prices = map[string]ModelPrice{}
	}
	return record.Prices, true, nil
}

func (s *Server) handleStatus(c *gin.Context) {
	events, deadLetters, err := s.store.Counts(c.Request.Context())
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	latestID, latestTimestamp, err := s.store.LatestCursor(c.Request.Context())
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{
		"service":           "embedded-usage-service",
		"dbPath":            s.cfg.DBPath,
		"events":            events,
		"deadLetters":       deadLetters,
		"latestId":          latestID,
		"latestTimestampMs": latestTimestamp,
	})
}

func (s *Server) handleQuotaCacheGet(c *gin.Context) {
	if c.Query("stats") == "1" || c.Query("stats") == "true" {
		stats, err := s.store.QuotaCacheStats(c.Request.Context())
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
			return
		}
		c.JSON(http.StatusOK, stats)
		return
	}

	provider := strings.TrimSpace(c.Query("provider"))
	fileName := strings.TrimSpace(c.Query("fileName"))
	entries, err := s.store.GetQuotaCache(c.Request.Context(), provider, fileName)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"items": entries})
}

func (s *Server) handleQuotaCachePut(c *gin.Context) {
	var entry QuotaCacheEntry
	if err := json.NewDecoder(c.Request.Body).Decode(&entry); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	entry.Provider = strings.TrimSpace(entry.Provider)
	entry.FileName = strings.TrimSpace(entry.FileName)
	if entry.Provider == "" || entry.FileName == "" || len(entry.Data) == 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "provider, fileName and data are required"})
		return
	}
	if err := s.store.SetQuotaCache(c.Request.Context(), entry); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"ok": true})
}

func (s *Server) handleQuotaCacheDelete(c *gin.Context) {
	provider := strings.TrimSpace(c.Query("provider"))
	fileName := strings.TrimSpace(c.Query("fileName"))
	if err := s.store.DeleteQuotaCache(c.Request.Context(), provider, fileName); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"ok": true})
}

func (s *Server) handleModelPricesGet(c *gin.Context) {
	prices, err := s.store.GetModelPrices(c.Request.Context())
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"prices": prices})
}

func (s *Server) handleModelPricesPut(c *gin.Context) {
	var payload struct {
		Prices map[string]ModelPrice `json:"prices"`
	}
	if err := json.NewDecoder(c.Request.Body).Decode(&payload); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	if payload.Prices == nil {
		payload.Prices = map[string]ModelPrice{}
	}
	if err := s.store.SetModelPrices(c.Request.Context(), payload.Prices); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"ok": true})
}
