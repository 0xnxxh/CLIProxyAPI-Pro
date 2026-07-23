package logging

import (
	"context"
	"net/http"

	"github.com/router-for-me/CLIProxyAPI/v7/internal/requestmeta"
)

func WithEndpoint(ctx context.Context, endpoint string) context.Context {
	return requestmeta.WithEndpoint(ctx, endpoint)
}

func GetEndpoint(ctx context.Context) string {
	return requestmeta.GetEndpoint(ctx)
}

func WithResponseStatusHolder(ctx context.Context) context.Context {
	return requestmeta.WithResponseStatusHolder(ctx)
}

func WithResponseHeadersHolder(ctx context.Context) context.Context {
	return requestmeta.WithResponseHeadersHolder(ctx)
}

func SetResponseStatus(ctx context.Context, status int) {
	requestmeta.SetResponseStatus(ctx, status)
}

func SetResponseHeaders(ctx context.Context, headers http.Header) {
	requestmeta.SetResponseHeaders(ctx, headers)
}

func GetResponseStatus(ctx context.Context) int {
	return requestmeta.GetResponseStatus(ctx)
}

func GetResponseHeaders(ctx context.Context) http.Header {
	return requestmeta.GetResponseHeaders(ctx)
}
