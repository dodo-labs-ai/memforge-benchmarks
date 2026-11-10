# frozen_string_literal: true

module API
  module Entities
    class UserSafe < Grape::Entity
      expose :id, :username
      expose :name
    end
  end
end
