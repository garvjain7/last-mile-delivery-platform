FROM golang:1.27-alpine AS builder

RUN CGO_ENABLED=0 go install github.com/minio/minio@latest

FROM alpine:3.22

RUN apk add --no-cache ca-certificates
COPY --from=builder /go/bin/minio /usr/local/bin/minio

EXPOSE 9000 9001
ENTRYPOINT ["minio"]
CMD ["server", "/data", "--console-address", ":9001"]
