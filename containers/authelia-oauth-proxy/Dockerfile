FROM golang:1.25-alpine AS builder

WORKDIR /app

COPY go.mod ./
RUN go mod download

COPY main.go ./
RUN CGO_ENABLED=0 GOOS=linux go build -a -installsuffix cgo -o oauth-proxy .

FROM gcr.io/distroless/static-debian12:nonroot

COPY --from=builder /app/oauth-proxy /oauth-proxy

EXPOSE 8080

USER nonroot:nonroot

ENTRYPOINT ["/oauth-proxy"]
