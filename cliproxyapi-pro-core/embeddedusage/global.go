package embeddedusage

import (
	"context"
	"fmt"
	"strings"
	"sync"
	"time"
)

var globalService *Service
var accountInspectionScheduleExporter func() (jsonBytes []byte, ok bool, err error)
var accountInspectionScheduleImporter func(jsonBytes []byte) error
var accountInspectionSnapshotExporter func() (jsonBytes []byte, ok bool, err error)
var accountInspectionSnapshotImporter func(jsonBytes []byte) error
var authRuntimeStateImporter func(cursors []RoutingCursorState, stats []AuthRuntimeStats) error
var globalStateMu sync.RWMutex
var globalStateWriterCancel context.CancelFunc
var globalStateWriterDone chan struct{}
var globalStateQueue chan runtimeStateMutation

type runtimeStateMutation struct {
	cursor *RoutingCursorState
	stats  *AuthRuntimeStats
	delete *runtimeStateDelete
	flush  chan error
}

type runtimeStateDelete struct {
	authID    string
	authIndex string
	fileName  string
	updatedAt int64
	done      chan error
}

func SetDefaultService(service *Service) {
	globalStateMu.Lock()
	if globalStateWriterCancel != nil {
		globalStateWriterCancel()
		globalStateWriterCancel = nil
	}
	globalService = service
	globalStateQueue = nil
	globalStateWriterDone = nil
	if service != nil && service.store != nil {
		parent := service.ctx
		if parent == nil {
			parent = context.Background()
		}
		ctx, cancel := context.WithCancel(parent)
		globalStateWriterCancel = cancel
		globalStateWriterDone = make(chan struct{})
		globalStateQueue = make(chan runtimeStateMutation, 1024)
		go runRuntimeStateWriter(ctx, service.store, globalStateQueue, globalStateWriterDone)
	}
	globalStateMu.Unlock()
}

func runRuntimeStateWriter(ctx context.Context, store *Store, queue <-chan runtimeStateMutation, done chan<- struct{}) {
	defer close(done)
	ticker := time.NewTicker(250 * time.Millisecond)
	defer ticker.Stop()
	cursors := make(map[string]RoutingCursorState)
	stats := make(map[string]AuthRuntimeStats)
	deletedAt := make(map[string]int64)
	merge := func(mutation runtimeStateMutation) {
		if mutation.cursor != nil {
			current, ok := cursors[mutation.cursor.CursorKey]
			if !ok || mutation.cursor.UpdatedAtMS >= current.UpdatedAtMS {
				cursors[mutation.cursor.CursorKey] = *mutation.cursor
			}
		}
		if mutation.stats != nil {
			if deleted := deletedAt[mutation.stats.AuthIndex]; deleted > 0 {
				if mutation.stats.UpdatedAtMS <= deleted {
					return
				}
				delete(deletedAt, mutation.stats.AuthIndex)
			}
			current, ok := stats[mutation.stats.AuthIndex]
			if !ok || mutation.stats.UpdatedAtMS >= current.UpdatedAtMS {
				stats[mutation.stats.AuthIndex] = *mutation.stats
			}
		}
	}
	flush := func() error {
		var firstErr error
		for key, state := range cursors {
			if err := store.SetRoutingCursorState(context.Background(), state); err != nil && firstErr == nil {
				firstErr = err
			}
			delete(cursors, key)
		}
		for key, item := range stats {
			if err := store.SetAuthRuntimeStats(context.Background(), item); err != nil && firstErr == nil {
				firstErr = err
			}
			delete(stats, key)
		}
		return firstErr
	}
	process := func(mutation runtimeStateMutation) {
		if mutation.flush != nil {
			mutation.flush <- flush()
			close(mutation.flush)
			return
		}
		if mutation.delete == nil {
			merge(mutation)
			return
		}
		flushErr := flush()
		err := store.DeleteAuthRuntimeState(context.Background(), mutation.delete.authID, mutation.delete.authIndex, mutation.delete.fileName)
		if err == nil {
			err = flushErr
		}
		if mutation.delete.authIndex != "" {
			deletedAt[mutation.delete.authIndex] = mutation.delete.updatedAt
		}
		mutation.delete.done <- err
		close(mutation.delete.done)
	}
	for {
		select {
		case <-ctx.Done():
			for {
				select {
				case mutation := <-queue:
					process(mutation)
				default:
					_ = flush()
					return
				}
			}
		case mutation := <-queue:
			process(mutation)
		case <-ticker.C:
			_ = flush()
		}
	}
}

func stopRuntimeStateWriter(service *Service) {
	globalStateMu.Lock()
	if globalService != service {
		globalStateMu.Unlock()
		return
	}
	cancel := globalStateWriterCancel
	done := globalStateWriterDone
	globalStateWriterCancel = nil
	globalStateWriterDone = nil
	globalStateQueue = nil
	globalService = nil
	globalStateMu.Unlock()
	if cancel != nil {
		cancel()
	}
	if done != nil {
		<-done
	}
}

func enqueueRuntimeState(mutation runtimeStateMutation) {
	globalStateMu.RLock()
	queue := globalStateQueue
	globalStateMu.RUnlock()
	if queue == nil {
		return
	}
	select {
	case queue <- mutation:
	default:
		// The next result/selection snapshot is cumulative and will supersede this one.
	}
}

func flushRuntimeStateWrites(ctx context.Context, store *Store) error {
	if ctx == nil {
		ctx = context.Background()
	}
	globalStateMu.RLock()
	var queue chan runtimeStateMutation
	if globalService != nil && globalService.store == store {
		queue = globalStateQueue
	}
	globalStateMu.RUnlock()
	if queue == nil {
		return nil
	}
	done := make(chan error, 1)
	select {
	case queue <- runtimeStateMutation{flush: done}:
	case <-ctx.Done():
		return ctx.Err()
	}
	select {
	case err := <-done:
		return err
	case <-ctx.Done():
		return ctx.Err()
	}
}

func SetAccountInspectionScheduleHandlers(exporter func() ([]byte, bool, error), importer func([]byte) error) {
	accountInspectionScheduleExporter = exporter
	accountInspectionScheduleImporter = importer
}

func SetAccountInspectionSnapshotHandlers(exporter func() ([]byte, bool, error), importer func([]byte) error) {
	accountInspectionSnapshotExporter = exporter
	accountInspectionSnapshotImporter = importer
}

func SetAuthRuntimeStateImportHandler(importer func([]RoutingCursorState, []AuthRuntimeStats) error) {
	authRuntimeStateImporter = importer
}

func defaultServer() *Server {
	globalStateMu.RLock()
	defer globalStateMu.RUnlock()
	if globalService == nil {
		return nil
	}
	return globalService.Server()
}

func SetQuotaCache(ctx context.Context, entry QuotaCacheEntry) error {
	globalStateMu.RLock()
	defer globalStateMu.RUnlock()
	if globalService == nil || globalService.store == nil {
		return fmt.Errorf("usage service is not available")
	}
	return globalService.store.SetQuotaCache(ctx, entry)
}

func GetQuotaCache(ctx context.Context, provider, fileName string) ([]QuotaCacheEntry, error) {
	globalStateMu.RLock()
	defer globalStateMu.RUnlock()
	if globalService == nil || globalService.store == nil {
		return nil, fmt.Errorf("usage service is not available")
	}
	return globalService.store.GetQuotaCache(ctx, provider, fileName)
}

func QueueRoutingCursorState(state RoutingCursorState) {
	state.CursorKey = strings.TrimSpace(state.CursorKey)
	state.LastAuthID = strings.TrimSpace(state.LastAuthID)
	if state.CursorKey == "" || state.LastAuthID == "" {
		return
	}
	if state.UpdatedAtMS <= 0 {
		state.UpdatedAtMS = time.Now().UnixMilli()
	}
	enqueueRuntimeState(runtimeStateMutation{cursor: &state})
}

func GetRoutingCursorState(ctx context.Context, cursorKey string) (RoutingCursorState, bool, error) {
	globalStateMu.RLock()
	defer globalStateMu.RUnlock()
	if globalService == nil || globalService.store == nil {
		return RoutingCursorState{}, false, nil
	}
	return globalService.store.GetRoutingCursorState(ctx, cursorKey)
}

func ListRoutingCursorStates(ctx context.Context) ([]RoutingCursorState, error) {
	globalStateMu.RLock()
	defer globalStateMu.RUnlock()
	if globalService == nil || globalService.store == nil {
		return nil, nil
	}
	return globalService.store.ListRoutingCursorStates(ctx)
}

func QueueAuthRuntimeStats(item AuthRuntimeStats) {
	if item.AuthIndex == "" || item.AuthID == "" {
		return
	}
	if item.UpdatedAtMS <= 0 {
		item.UpdatedAtMS = time.Now().UnixMilli()
	}
	enqueueRuntimeState(runtimeStateMutation{stats: &item})
}

func GetAuthRuntimeStats(ctx context.Context, authIndex, authID string) (AuthRuntimeStats, bool, error) {
	globalStateMu.RLock()
	defer globalStateMu.RUnlock()
	if globalService == nil || globalService.store == nil {
		return AuthRuntimeStats{}, false, nil
	}
	return globalService.store.GetAuthRuntimeStats(ctx, authIndex, authID)
}

func DeleteAuthRuntimeState(ctx context.Context, authID, authIndex, fileName string) error {
	globalStateMu.RLock()
	service := globalService
	queue := globalStateQueue
	globalStateMu.RUnlock()
	if service == nil || service.store == nil {
		return nil
	}
	if queue == nil {
		return service.store.DeleteAuthRuntimeState(ctx, authID, authIndex, fileName)
	}
	deletion := &runtimeStateDelete{
		authID: authID, authIndex: authIndex, fileName: fileName,
		updatedAt: time.Now().UnixMilli(), done: make(chan error, 1),
	}
	select {
	case queue <- runtimeStateMutation{delete: deletion}:
	case <-ctx.Done():
		return ctx.Err()
	}
	select {
	case err := <-deletion.done:
		return err
	case <-ctx.Done():
		return ctx.Err()
	}
}
